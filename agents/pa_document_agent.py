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
import logging
from datetime import datetime
from utils.agent_logger import log_event
from utils.llm_util import get_keys, get_model_order
import time

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from db.session import SessionLocal
from crud.crud_case import get_case
from crud.crud_ehr import get_ehr

from prompts.pa_document_prompts import (
    get_cover_letter_prompt,
    get_clinical_summary_prompt,
    get_checklist_prompt,
)
from tools.ehr_fetcher import fetch_extracted_data_by_case
from tools.pdf_extractor import extract_raw_text

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# LLM SINGLETON
# ─────────────────────────────────────────

_llm = None

def _get_llm(api_key=None, model_name: str | None = None):
    if not api_key:
        api_key = os.getenv("GOOGLE_API_KEY")
    if not model_name:
        model_name = get_model_order("pa_document")[0]
    return ChatGoogleGenerativeAI(
        model=model_name,
        temperature=0.3,
        google_api_key=api_key,
    )


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
    """Format a prompt template and call the LLM with key rotation."""
    all_keys = get_keys()
    model_order = get_model_order("pa_document")
    messages = prompt_template.format_messages(**variables)

    for key_index, current_key in enumerate(all_keys):
        for model_name in model_order:
            try:
                llm = _get_llm(api_key=current_key, model_name=model_name)
                response = llm.invoke(messages)
                return response.content.strip()
            except Exception as e:
                error_text = str(e)
                if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
                    print(f"[pa_document_agent] model={model_name} exhausted on key {key_index + 1}. Trying next model on same key...")
                    continue
                print(f"[pa_document_agent] model={model_name} key {key_index + 1} failed: {error_text}")
                continue
    raise Exception("All API keys exhausted or fatal error.")


# ─────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────

def generate_pa_content(case_id: str, payer_name: str | None = None, pdf_path: str | None = None) -> dict:
    """
    Generate all LLM content for the PA document.

    Args:
        case_id:  Case identifier — used to fetch EHR data.
        payer_name: Insurance payer name (Aetna, Cigna, etc.) for policy-specific rules.
                    If not supplied, extracted from EHR data.
        pdf_path: Path to policy PDF (optional, not used for policy selection).

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
        message    = f"Prior Auth package generation triggered for {payer_name}"
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
    
    # Extract payer from EHR if not provided
    if not payer_name and isinstance(ehr, dict):
        payer_name = ehr.get("payer_name") or ehr.get("insurance_company")
    
    # Robust Fallback: Try fetching raw EHR data if extracted_data is empty
    if not ehr:
        print(f"[pa_document_agent] EHR extracted data empty for {case_id}, trying raw EHR lookup...")
        with SessionLocal() as db:
            db_case = get_case(db, case_id)
            if db_case:
                # 1. Try raw EHR table
                raw_ehr = get_ehr(db, db_case.patient_id)
                if raw_ehr:
                    print(f"[pa_document_agent] Found raw EHR for patient {db_case.patient_id}")
                    ehr = raw_ehr.to_dict()
                else:
        # 2. Last resort: Basic case model placeholders
                    print(f"[pa_document_agent] No raw EHR found, using Case placeholders.")
                    ehr["patient_id"] = db_case.patient_id
                    ehr["patient_first_name"] = "Patient"
                    ehr["patient_last_name"] = str(db_case.patient_id)
                    ehr["date_of_birth"] = "N/A (Update in Records)"
                    ehr["insurance_company"] = "N/A"
                    
                    # Get payer from case if not in EHR
                    if not payer_name:
                        payer_name = db_case.insurance_company
    
    # Bundle pre-summarized data
    summarized_data_path = os.path.join(backend_dir, "uploads", "all_summarized_data.json")
    summarized_evidence_text = ""
    if os.path.exists(summarized_data_path):
        try:
            with open(summarized_data_path, 'r', encoding='utf-8') as f:
                summarized_data = json.load(f)
            if summarized_data and isinstance(summarized_data, list):
                summarized_evidence_text = "\n\n### PRE-SUMMARIZED PATIENT PDF EVIDENCE:\n"
                for summary_item in summarized_data:
                    fname = summary_item.get("file", "Unknown File")
                    summary = summary_item.get("summary", "No summary found.")
                    if "error" in summary_item:
                        continue
                    summarized_evidence_text += f"\n--- {fname} ---\n{summary}\n"
        except Exception as e:
            print(f"[pa_document_agent] Failed to load summarized PDFs: {e}")

    ehr_text = _ehr_to_text(ehr) + summarized_evidence_text
    
    log_event(
        case_id     = case_id,
        agent_name  = "PA_DOCUMENT_AGENT",
        event       = "EHR_FETCH_COMPLETED",
        status      = "SUCCESS",
        duration_ms = int((time.time() - ehr_fetch_start) * 1000)
    )

    # 2. Extract policy details and pa rules
    pdf_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "PA_DOCUMENT_AGENT",
        event      = "POLICY_RULES_LOADING_STARTED",
        status     = "RUNNING"
    )
    pa_format = "{}"
    policy_rules = "[]"
    
    try:
        from tools.policy_retriever import search_policy_criteria
        pa_format = search_policy_criteria(doc_type="pa_document_format", payer=payer_name)
        req_docs = search_policy_criteria(doc_type="required_documents", payer=payer_name)
        elig_crit = search_policy_criteria(doc_type="eligibility_criteria", payer=payer_name)
        policy_rules = f"{req_docs}\n\n{elig_crit}"
        
        log_event(
            case_id     = case_id,
            agent_name  = "PA_DOCUMENT_AGENT",
            event       = "POLICY_RULES_LOADING_COMPLETED",
            status      = "SUCCESS",
            message     = f"Policy data loaded for {payer_name}",
            duration_ms = int((time.time() - pdf_start) * 1000)
        )
    except ValueError as e:
        logger.warning(f"[pa_document_agent] Policy data unavailable for {payer_name}: {e}. Using defaults.")
        log_event(
            case_id    = case_id,
            agent_name = "PA_DOCUMENT_AGENT",
            event      = "POLICY_RULES_LOADING_PARTIAL",
            status     = "PARTIAL",
            message    = f"Policy data unavailable for {payer_name}, using defaults"
        )
        print(f"[pa_document_agent] Policy rules loading partial (using defaults): {e}")
        pa_format = "{}"
        policy_rules = "[]"
    except Exception as e:
        logger.error(f"[pa_document_agent] Unexpected RAG error: {e}")
        log_event(
            case_id    = case_id,
            agent_name = "PA_DOCUMENT_AGENT",
            event      = "POLICY_RULES_LOADING_FAILED",
            status     = "FAILED",
            message    = str(e)
        )
        print(f"[pa_document_agent] Policy rules loading failed: {e}")
        pa_format = "{}"
        policy_rules = "[]"

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
        {"ehr_data": ehr_text, "date": today, "pa_format": pa_format},
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
        {"ehr_data": ehr_text, "pa_format": pa_format},
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
        {"ehr_data": ehr_text, "policy_rules": policy_rules},
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
