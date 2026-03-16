"""
PA Document Agent

Uses Gemini to generate the text content for the three LLM sections
of the Prior Authorization package:
  1. Cover Letter   — formal medical necessity letter
  2. Clinical Summary — narrative of patient history + clinical rationale
  3. Checklist       — every insurance required item, ticked with evidence
"""

import os
import sys
import json
import re
from datetime import datetime
from utils.agent_logger import log_event
import time

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from prompts.pa_document_prompts import (
    get_cover_letter_prompt,
    get_clinical_summary_prompt,
    get_checklist_prompt,
)
from tools.ehr_fetcher import fetch_extracted_data_by_case
from tools.pdf_extractor import extract_raw_text

# ─────────────────────────────────────────
# LLM SINGLETON
# ─────────────────────────────────────────

_llm = None

def _get_llm():
    global _llm
    if _llm:
        return _llm
    load_dotenv(os.path.join(backend_dir, ".env"))
    api_key = os.getenv("GOOGLE_API_KEY")
    _llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-lite",
        temperature=0.3,
        google_api_key=api_key,
    )
    return _llm


def _ehr_to_text(ehr: dict) -> str:
    """Flatten EHR dict to a readable key: value block for the LLM."""
    if not ehr:
        return "No EHR data available."
    lines = []
    for k, v in ehr.items():
        if v is not None and v != "" and v != {} and v != []:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _invoke(prompt_template, variables: dict) -> str:
    """Format a prompt template and call the LLM."""
    llm = _get_llm()
    messages = prompt_template.format_messages(**variables)
    response = llm.invoke(messages)
    return response.content.strip()


# ─────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────

def generate_pa_content(case_id: str, pdf_path: str | None = None) -> dict:
    """
    Generate all LLM content for the PA document.

    Args:
        case_id:  Case identifier — used to fetch EHR data.
        pdf_path: Path to policy PDF — used to build the checklist.
                  Defaults to aetna/test_doc.pdf if not supplied.

    Returns:
        {
          "ehr":              dict,    # raw EHR data
          "cover_letter":     str,     # LLM-written letter
          "clinical_summary": str,     # LLM-written narrative
          "checklist":        list[{item, met, evidence}],
        }
    """
    if not pdf_path:
        pdf_path = os.path.join(backend_dir, "policy-pdfs", "aetna", "test_doc.pdf")

    agent_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "PA_DOCUMENT_AGENT",
        event      = "DOCUMENT_GENERATION_STARTED",
        status     = "RUNNING",
        message    = "Prior Auth package generation triggered"
    )

    # 1. Fetch EHR
    ehr_fetch_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "PA_DOCUMENT_AGENT",
        event      = "EHR_FETCH_STARTED",
        status     = "RUNNING"
    )
    ehr = fetch_extracted_data_by_case(case_id) or {}
    ehr_text = _ehr_to_text(ehr)
    log_event(
        case_id     = case_id,
        agent_name  = "PA_DOCUMENT_AGENT",
        event       = "EHR_FETCH_COMPLETED",
        status      = "SUCCESS",
        duration_ms = int((time.time() - ehr_fetch_start) * 1000)
    )

    # 2. Extract policy text (for checklist)
    pdf_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "PA_DOCUMENT_AGENT",
        event      = "PDF_EXTRACTION_STARTED",
        status     = "RUNNING"
    )
    policy_text = ""
    if os.path.exists(pdf_path):
        try:
            policy_text = extract_raw_text(pdf_path)
            log_event(
                case_id     = case_id,
                agent_name  = "PA_DOCUMENT_AGENT",
                event       = "PDF_EXTRACTION_COMPLETED",
                status      = "SUCCESS",
                duration_ms = int((time.time() - pdf_start) * 1000)
            )
        except Exception as e:
            log_event(
                case_id    = case_id,
                agent_name = "PA_DOCUMENT_AGENT",
                event      = "PDF_EXTRACTION_FAILED",
                status     = "FAILED",
                message    = str(e)
            )
            print(f"[pa_document_agent] PDF extraction failed: {e}")
            policy_text = "Policy PDF could not be read."
    else:
        log_event(
            case_id    = case_id,
            agent_name = "PA_DOCUMENT_AGENT",
            event      = "PDF_EXTRACTION_FAILED",
            status     = "FAILED",
            message    = "Policy PDF not found"
        )
        policy_text = "Policy PDF not found."

    today = datetime.now().strftime("%B %d, %Y")

    # 3. Generate Cover Letter
    print("[pa_document_agent] Generating cover letter...")
    cl_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "PA_DOCUMENT_AGENT",
        event      = "COVER_LETTER_GENERATION_STARTED",
        status     = "RUNNING"
    )
    cover_letter = _invoke(
        get_cover_letter_prompt(),
        {"ehr_data": ehr_text, "date": today},
    )
    log_event(
        case_id     = case_id,
        agent_name  = "PA_DOCUMENT_AGENT",
        event       = "COVER_LETTER_GENERATION_COMPLETED",
        status      = "SUCCESS",
        duration_ms = int((time.time() - cl_start) * 1000)
    )

    # 4. Generate Clinical Summary
    print("[pa_document_agent] Generating clinical summary...")
    cs_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "PA_DOCUMENT_AGENT",
        event      = "CLINICAL_SUMMARY_GENERATION_STARTED",
        status     = "RUNNING"
    )
    clinical_summary = _invoke(
        get_clinical_summary_prompt(),
        {"ehr_data": ehr_text},
    )
    log_event(
        case_id     = case_id,
        agent_name  = "PA_DOCUMENT_AGENT",
        event       = "CLINICAL_SUMMARY_GENERATION_COMPLETED",
        status      = "SUCCESS",
        duration_ms = int((time.time() - cs_start) * 1000)
    )

    # 5. Generate Checklist
    print("[pa_document_agent] Generating checklist...")
    ch_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "PA_DOCUMENT_AGENT",
        event      = "CHECKLIST_GENERATION_STARTED",
        status     = "RUNNING"
    )
    raw_checklist = _invoke(
        get_checklist_prompt(),
        {"ehr_data": ehr_text, "policy_text": policy_text[:4000]},
    )
    log_event(
        case_id     = case_id,
        agent_name  = "PA_DOCUMENT_AGENT",
        event       = "CHECKLIST_GENERATION_COMPLETED",
        status      = "SUCCESS",
        duration_ms = int((time.time() - ch_start) * 1000)
    )

    # Parse checklist JSON — gracefully fall back if LLM output is imperfect
    checklist = []
    try:
        # Strip markdown code fences if present
        clean = re.sub(r"```(?:json)?|```", "", raw_checklist).strip()
        checklist = json.loads(clean)
    except Exception as e:
        print(f"[pa_document_agent] Checklist JSON parse failed: {e}")
        checklist = [{"item": "See generated summary", "met": True, "evidence": raw_checklist[:300]}]

    log_event(
        case_id     = case_id,
        agent_name  = "PA_DOCUMENT_AGENT",
        event       = "DOCUMENT_GENERATION_COMPLETED",
        status      = "SUCCESS",
        message     = f"Generated cover letter, summary, and {len(checklist)} checklist items",
        duration_ms = int((time.time() - agent_start) * 1000)
    )

    return {
        "ehr": ehr,
        "cover_letter": cover_letter,
        "clinical_summary": clinical_summary,
        "checklist": checklist,
    }
