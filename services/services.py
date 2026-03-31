"""
services.py — Core Business Logic & Document Processing
========================================================

This module acts as the 'Service Layer' of the application. It contains 
the heavy-lifting logic for document summarization, PDF generation, 
and EHR data extraction that supports the AI Orchestrator.

Major Service Groups:
--------------------
1. **Authentication**: Secure verification of user credentials.
2. **EHR Extraction**: Intelligent mapping of raw Electronic Health 
   Record data into a structured format for the AI agents.
3. **Summarization**: High-performance, concurrent processing of 
   user-uploaded medical PDFs using LLMs and hash-based caching.
4. **PDF Generation**: Orchestrates the creation of the final 
   Prior Authorization request package using ReportLab.
"""

import os
import sys
import json
import asyncio
import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from sqlalchemy.orm import Session

# ReportLab imports for PDF generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)

# Internal imports
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from core.security import verify_password, get_password_hash
from db import get_user_by_email
from db import get_ehr
from db import create_extracted_data, get_extracted_data
from db import get_case
from models.user import User
from schemas.extracted_data import ExtractedDataCreate
from utils.llm_util import RobustLLM
from utils.cache_manager import pdf_cache
from prompts import get_pdf_summarization_prompt

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 1. AUTHENTICATION SERVICE
# ─────────────────────────────────────────────────────────────────────────────

class AuthenticationService:
    """Service for handling authentication operations."""

    @staticmethod
    def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
        """
        Authenticate a user with username and password against the database.
        """
        user = get_user_by_email(db, email=username)
        if not user:
            return None

        if not verify_password(password, user.hashed_password, username=username):
            return None

        if not user.is_active:
            return None

        return user

authentication_service = AuthenticationService()

# ─────────────────────────────────────────────────────────────────────────────
# 2. EHR EXTRACTION SERVICE
# ─────────────────────────────────────────────────────────────────────────────

def fill_extracted_data_from_ehr(db: Session, patient_id: str, case_id: str) -> None:
    """
    Look up the EHR record for *patient_id* and create an ExtractedData row
    linked to *case_id*.
    """
    if get_extracted_data(db, case_id):
        return

    ehr = get_ehr(db, patient_id)
    if not ehr and patient_id.startswith("PA-"):
        fallback_id = "PT-" + patient_id[3:]
        ehr = get_ehr(db, fallback_id)
            
    if not ehr:
        logger.warning(f"[extraction_service] No EHR record found for patient_id={patient_id!r}")
        return

    payload = ExtractedDataCreate(
        case_id=case_id,
        patient_id=ehr.patient_id,
        patient_first_name=ehr.patient_first_name,
        patient_last_name=ehr.patient_last_name,
        patient_dob=ehr.date_of_birth,
        patient_gender=ehr.gender,
        payer_name=ehr.insurance_company,
        member_id=ehr.member_id,
        policy_number=ehr.policy_number,
        group_number=ehr.group_number,
        plan_name=ehr.plan_name,
        physician_name=ehr.physician_name,
        physician_npi=ehr.physician_npi,
        physician_specialty=ehr.physician_specialty,
        facility_name=ehr.facility_name,
        primary_icd10_code=ehr.icd10_code,
        primary_diagnosis=ehr.diagnosis,
        cpt_code=ehr.cpt_code,
        lab_results=ehr.lab_results,
        ehr_filled_at=datetime.now(timezone.utc),
    )

    logger.info(f"[extraction_service] --- Data Extraction Started for {case_id} ---")
    create_extracted_data(db, payload)

    # Sync to Case
    db_case = get_case(db, case_id)
    if db_case:
        updated = False
        if not db_case.insurance_company and ehr.insurance_company:
            db_case.insurance_company = ehr.insurance_company
            updated = True
        if not db_case.cpt_code and ehr.cpt_code:
            db_case.cpt_code = ehr.cpt_code
            updated = True
        if not db_case.icd10_code and ehr.icd10_code:
            db_case.icd10_code = ehr.icd10_code
            updated = True
        if not db_case.patient_name and (ehr.patient_first_name or ehr.patient_last_name):
            db_case.patient_name = f"{ehr.patient_first_name} {ehr.patient_last_name}".strip()
            updated = True
            
        if updated:
            db.add(db_case)
            db.commit()

    logger.info(f"[extraction_service] --- Data Extraction Completed for {case_id} ---")

# ─────────────────────────────────────────────────────────────────────────────
# 3. SUMMARIZATION SERVICE
# ─────────────────────────────────────────────────────────────────────────────

async def get_file_hash(file_path: str) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

async def summarize_single_pdf(pdf_path: str, llm, prompt_template) -> Dict[str, Any]:
    file_name = os.path.basename(pdf_path)
    try:
        file_hash = await get_file_hash(pdf_path)
        cache_key = f"summary_v1_{file_hash}"
        cached_summary = pdf_cache.get(cache_key)
        
        if cached_summary:
            return {"file": file_name, "summary": cached_summary, "cached": True}

        reader = PdfReader(pdf_path)
        text = "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])
        
        if not text.strip():
            return {"file": file_name, "summary": "No text found.", "error": "Empty"}

        prompt = prompt_template.invoke({"document_text": text})
        response = await llm.ainvoke(prompt)
        summary = response.content
        pdf_cache.set(cache_key, summary)
        
        return {"file": file_name, "summary": summary, "cached": False}
    except Exception as e:
        return {"file": file_name, "error": str(e)}

async def summarize_case_documents(case_id: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
    target_dir = os.path.join(backend_dir, "uploads", case_id)
    output_file = os.path.join(backend_dir, "uploads", f"{case_id}_summaries.json")
    
    if not os.path.exists(target_dir): return []
    pdf_files = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.lower().endswith('.pdf')]
    if not pdf_files: return []

    llm = RobustLLM.get_llm_for_task(task="summarization")
    prompt = get_pdf_summarization_prompt()
    results = await asyncio.gather(*[summarize_single_pdf(pdf, llm, prompt) for pdf in pdf_files])

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=4)
    except: pass
    return results

# ─────────────────────────────────────────────────────────────────────────────
# 4. ASYNC FILE PROCESSING SERVICE
# ─────────────────────────────────────────────────────────────────────────────

class AsyncFileExtractor:
    def __init__(self, max_concurrency: int = 5):
        self.max_concurrency = max_concurrency
    
    async def extract_text_from_file(self, file_path: str, max_page_concurrency: int = 3) -> str:
        try:
            reader = PdfReader(file_path)
            if not reader.pages: return ""
            semaphore = asyncio.Semaphore(max_page_concurrency)
            async def bounded_extract(idx):
                async with semaphore:
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(None, reader.pages[idx].extract_text) or ""
            
            results = await asyncio.gather(*[bounded_extract(i) for i in range(len(reader.pages))])
            return "\n".join(filter(None, results))
        except Exception as e:
            logger.error(f"Error extracting {file_path}: {e}")
            return ""
    
    async def extract_multiple_files(self, file_paths: List[str]) -> Dict[str, str]:
        semaphore = asyncio.Semaphore(self.max_concurrency)
        async def bounded(f):
            async with semaphore:
                return f, await self.extract_text_from_file(f)
        results = await asyncio.gather(*[bounded(f) for f in file_paths])
        return dict(results)

async def extract_files_batch(file_paths: List[str], max_concurrency: int = 5) -> Dict[str, str]:
    extractor = AsyncFileExtractor(max_concurrency=max_concurrency)
    return await extractor.extract_multiple_files(file_paths)

# ─────────────────────────────────────────────────────────────────────────────
# 5. PDF GENERATOR SERVICE
# ─────────────────────────────────────────────────────────────────────────────

PRIMARY = colors.HexColor("#38A3A5"); DARK = colors.HexColor("#1a1a2e"); LIGHT_BG = colors.HexColor("#f0fafa")
MET_GREEN = colors.HexColor("#16a34a"); MISS_RED = colors.HexColor("#dc2626"); GREY = colors.HexColor("#64748b")

def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", fontSize=20, textColor=PRIMARY, fontName="Helvetica-Bold"),
        "section_header": ParagraphStyle("section_header", fontSize=13, textColor=PRIMARY, fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6),
        "body": ParagraphStyle("body", fontSize=10, textColor=DARK, leading=16, spaceAfter=6, alignment=TA_JUSTIFY),
        "meta": ParagraphStyle("meta", fontSize=9, textColor=GREY, leading=13, spaceAfter=4),
        "table_cell": ParagraphStyle("table_cell", fontSize=9, textColor=DARK, leading=12, alignment=TA_LEFT),
        "checklist_header": ParagraphStyle("checklist_header", fontSize=10, textColor=colors.white, fontName="Helvetica-Bold"),
    }

def _header(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(PRIMARY); canvas.rect(0, letter[1] - 0.6 * inch, letter[0], 0.6 * inch, fill=1, stroke=0)
    canvas.setFillColor(colors.white); canvas.setFont("Helvetica-Bold", 14); canvas.drawString(0.5 * inch, letter[1] - 0.4 * inch, "AutoAuth")
    canvas.restoreState()

def generate_pa_pdf(case_id: str, content: dict, uploaded_file_paths: Optional[List[str]] = None, output_dir: Optional[str] = None) -> str:
    if not output_dir:
        output_dir = os.path.join(backend_dir, "uploads", "generated")
    os.makedirs(output_dir, exist_ok=True)
    base_path = os.path.join(output_dir, f"PA_{case_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
    
    doc = SimpleDocTemplate(base_path, pagesize=letter, topMargin=0.9*inch, bottomMargin=0.6*inch)
    styles = _styles(); story = []
    
    # Simple versions of builders for brevity in consolidation
    story.append(Paragraph("PRIOR AUTHORIZATION REQUEST", styles["title"]))
    story.append(Paragraph("Cover Letter", styles["section_header"]))
    for para in content.get("cover_letter", "").split("\n"):
        if para.strip(): story.append(Paragraph(para.strip(), styles["body"]))
    
    story.append(PageBreak())
    story.append(Paragraph("Clinical Summary", styles["title"]))
    story.append(Paragraph(content.get("clinical_summary", ""), styles["body"]))
    
    doc.build(story, onFirstPage=_header, onLaterPages=_header)
    
    # Merge logic
    if uploaded_file_paths:
        try:
            writer = PdfWriter()
            for page in PdfReader(base_path).pages: writer.add_page(page)
            for path in [p for p in uploaded_file_paths if p.lower().endswith(".pdf") and os.path.exists(p)]:
                for page in PdfReader(path).pages: writer.add_page(page)
            with open(base_path, "wb") as f: writer.write(f)
        except Exception as e: logger.error(f"Merge failed: {e}")
        
    return base_path
