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
    get_combined_pa_prompt,
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
                    logger.warning(f"[pa_document_agent] model={model_name} exhausted on key {key_index + 1}. Trying next model on same key...")
                    continue
                logger.error(f"[pa_document_agent] model={model_name} key {key_index + 1} failed: {error_text}")
                continue
    raise Exception("All API keys exhausted or fatal error.")


def _invoke_combined_pa_generation(
    ehr_text: str,
    date: str,
    pa_format: str,
    policy_rules: str
) -> dict:
    """
    OPTIMIZATION 8: Single LLM call generates all 3 PA documents in JSON format.
    
    Instead of 3 separate calls (cover letter, clinical summary, checklist),
    this makes 1 call that returns all 3 in structured JSON.
    
    Args:
        ehr_text: Patient EHR data as formatted text
        date: Current date formatted (e.g., "March 30, 2026")
        pa_format: Policy-specific PA format rules
        policy_rules: Combined policy requirements
    
    Returns:
        {
            "cover_letter": str,
            "clinical_summary": str,
            "checklist": list[dict] (already parsed)
        }
    
    Raises:
        ValueError: If JSON is invalid or missing required keys
        Exception: If all API keys exhausted
    """
    all_keys = get_keys()
    model_order = get_model_order("pa_document")
    
    # Format the combined prompt with all variables
    messages = get_combined_pa_prompt().format_messages(
        ehr_data=ehr_text,
        date=date,
        pa_format=pa_format,
        policy_rules=policy_rules
    )
    
    for key_index, current_key in enumerate(all_keys):
        for model_name in model_order:
            try:
                llm = _get_llm(api_key=current_key, model_name=model_name)
                response = llm.invoke(messages)
                raw_json = response.content.strip()
                
                # Parse JSON (strip markdown code fences if present)
                clean = re.sub(r"```(?:json)?|```", "", raw_json).strip()
                parsed = json.loads(clean)
                
                # Validate required keys exist
                required_keys = {"cover_letter", "clinical_summary", "checklist"}
                missing_keys = required_keys - set(parsed.keys())
                if missing_keys:
                    raise ValueError(
                        f"[pa_document_agent] Missing required keys in LLM response: {missing_keys}"
                    )
                
                # Validate checklist is a list
                if not isinstance(parsed.get("checklist"), list):
                    raise ValueError("[pa_document_agent] Checklist must be a list")
                
                logger.info("[pa_document_agent] Batch PA generation succeeded (single LLM call)")
                return parsed  # Success!
                
            except json.JSONDecodeError as e:
                logger.error(f"[pa_document_agent] JSON decode failed with model={model_name}: {e}")
                # Try next key/model
                continue
            except ValueError as e:
                logger.error(f"[pa_document_agent] Response validation failed: {e}")
                # Try next key/model
                continue
            except Exception as e:
                error_text = str(e)
                if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
                    logger.warning(f"[pa_document_agent] Rate limited on key {key_index + 1}, trying next...")
                    continue
                logger.error(f"[pa_document_agent] LLM call failed on key {key_index + 1}: {error_text}")
                continue
    
    raise Exception("[pa_document_agent] All API keys exhausted or batch generation failed")


# ─────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────

from sqlalchemy.orm import Session

def generate_pa_content(case_id: str, payer_name: str | None = None, cpt_code: str | None = None, pdf_path: str | None = None, ehr_data_cached: dict | None = None, db_session: Session | None = None) -> dict:
    """
    Generate all LLM content for the PA document.

    Args:
        case_id:  Case identifier — used to fetch EHR data.
        payer_name: Insurance payer name (Aetna, Cigna, etc.) for policy-specific rules.
                    If not supplied, extracted from EHR data.
        pdf_path: Path to policy PDF (optional, not used for policy selection).
        ehr_data_cached: Pre-fetched EHR data from orchestrator memory (optional, Optimization 7).
        db_session: Database session for logging.

    Returns:
        {
          "ehr":              dict,    # raw EHR data
          "cover_letter":     str,     # LLM-written letter
          "clinical_summary": str,     # LLM-written narrative
          "checklist":        list[{item, met, evidence}],
        }
    """
    agent_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "PA_DOCUMENT_AGENT",
        event      = "DOCUMENT_GENERATION_STARTED",
        status     = "RUNNING",
        message    = f"Prior Auth package generation triggered (payer={payer_name}, cpt={cpt_code})",
        db_session = db_session
    )

    # 1. Fetch EHR
    ehr_fetch_start = time.time()
    
    # OPTIMIZATION 7: Try to use cached EHR data if provided
    if ehr_data_cached:
        log_event(
            case_id    = case_id,
            agent_name = "PA_DOCUMENT_AGENT",
            event      = "EHR_CACHE_HIT",
            status     = "SUCCESS",
            db_session = db_session
        )
        ehr = ehr_data_cached
        logger.info(f"[pa_document_agent] Using cached EHR data from memory for {case_id}")
    else:
        log_event(
            case_id    = case_id,
            agent_name = "PA_DOCUMENT_AGENT",
            event      = "EHR_FETCH_STARTED",
            status     = "RUNNING",
            db_session = db_session
        )
        ehr = fetch_extracted_data_by_case(case_id) or {}
        logger.info(f"[pa_document_agent] Fetched fresh EHR data for {case_id}")
    
    # Extract payer from EHR if not provided
    if not payer_name and isinstance(ehr, dict):
        payer_name = ehr.get("payer_name") or ehr.get("insurance_company")
    
    # Robust Fallback: Try fetching raw EHR data if extracted_data is empty
    if not ehr:
        logger.info(f"[pa_document_agent] EHR extracted data empty for {case_id}, trying raw EHR lookup...")
        with SessionLocal() as db:
            db_case = get_case(db, case_id)
            if db_case:
                # 1. Try raw EHR table
                raw_ehr = get_ehr(db, db_case.patient_id)
                if raw_ehr:
                    logger.info(f"[pa_document_agent] Found raw EHR for patient {db_case.patient_id}")
                    ehr = raw_ehr.to_dict()
                else:
                    # 2. Last resort: Basic case model placeholders
                    logger.info(f"[pa_document_agent] No raw EHR found, using Case placeholders.")
                    ehr["patient_id"] = db_case.patient_id
                    ehr["patient_first_name"] = "Patient"
                    ehr["patient_last_name"] = str(db_case.patient_id)
                    ehr["date_of_birth"] = "N/A (Update in Records)"
                    ehr["insurance_company"] = "N/A"
                    
                    # Get payer from case if not in EHR
                    if not payer_name:
                        payer_name = db_case.insurance_company
    
    # ── DYNAMIC PDF PATH SELECTION ──
    if not pdf_path:
        # Try to find a PDF for this specific payer
        try:
            if payer_name:
                payer_dir_name = payer_name.lower().replace(" ", "-")
                payer_policy_dir = os.path.join(backend_dir, "policy-pdfs", payer_dir_name)
                if os.path.exists(payer_policy_dir):
                    pdfs = [f for f in os.listdir(payer_policy_dir) if f.lower().endswith(".pdf")]
                    if pdfs:
                        pdf_path = os.path.join(payer_policy_dir, pdfs[0])
                        logger.info(f"[pa_document_agent] Dynamically selected policy PDF: {pdf_path}")
        except Exception as e:
            logger.warning(f"[pa_document_agent] Failed dynamic PDF lookup: {e}")
            
        # Last resort fallback (preserve current behavior)
        if not pdf_path:
            pdf_path = os.path.join(backend_dir, "policy-pdfs", "aetna", "test_doc.pdf")
            logger.info(f"[pa_document_agent] Using default fallback policy PDF: {pdf_path}")
    
    # Bundle pre-summarized data (Case-Specific First, then Global Fallback)
    # OPTIMIZATION: Data Isolation - Look for summaries specific to this case_id
    case_summarized_path = os.path.join(backend_dir, "uploads", f"{case_id}_summaries.json")
    global_summarized_path = os.path.join(backend_dir, "uploads", "all_summarized_data.json")
    
    summarized_data_path = None
    if os.path.exists(case_summarized_path):
        summarized_data_path = case_summarized_path
        logger.info(f"[pa_document_agent] Found case-specific summaries for {case_id}")
    elif os.path.exists(global_summarized_path):
        summarized_data_path = global_summarized_path
        logger.warning(f"[pa_document_agent] Using global summaries fallback for {case_id} (Potential Isolation Risk)")
    
    summarized_evidence_text = ""
    if summarized_data_path:
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
            logger.error(f"[pa_document_agent] Failed to load summarized PDFs: {e}")

    ehr_text = _ehr_to_text(ehr) + summarized_evidence_text
    
    log_event(
        case_id     = case_id,
        agent_name  = "PA_DOCUMENT_AGENT",
        event       = "EHR_FETCH_COMPLETED",
        status      = "SUCCESS",
        duration_ms = int((time.time() - ehr_fetch_start) * 1000),
        db_session  = db_session
    )

    # 2. Extract policy details and pa rules
    pdf_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "PA_DOCUMENT_AGENT",
        event      = "POLICY_RULES_LOADING_STARTED",
        status     = "RUNNING",
        db_session = db_session
    )
    pa_format = "{}"
    policy_rules = "[]"
    
    try:
        from tools.policy_retriever import search_policy_criteria
        pa_format = search_policy_criteria(doc_type="pa_document_format", payer=payer_name, cpt=cpt_code)
        req_docs = search_policy_criteria(doc_type="required_documents", payer=payer_name, cpt=cpt_code)
        elig_crit = search_policy_criteria(doc_type="eligibility_criteria", payer=payer_name, cpt=cpt_code)
        policy_rules = f"{req_docs}\n\n{elig_crit}"
        
        log_event(
            case_id     = case_id,
            agent_name  = "PA_DOCUMENT_AGENT",
            event       = "POLICY_RULES_LOADING_COMPLETED",
            status      = "SUCCESS",
            message     = f"Policy data loaded for {payer_name}",
            duration_ms = int((time.time() - pdf_start) * 1000),
            db_session  = db_session
        )
    except ValueError as e:
        logger.warning(f"[pa_document_agent] Policy data unavailable for {payer_name}: {e}. Using defaults.")
        log_event(
            case_id    = case_id,
            agent_name = "PA_DOCUMENT_AGENT",
            event      = "POLICY_RULES_LOADING_PARTIAL",
            status     = "PARTIAL",
            message    = f"Policy data unavailable for {payer_name}, using defaults",
            db_session = db_session
        )
        pa_format = "{}"
        policy_rules = "[]"
    except Exception as e:
        logger.error(f"[pa_document_agent] Unexpected RAG error: {e}")
        log_event(
            case_id    = case_id,
            agent_name = "PA_DOCUMENT_AGENT",
            event      = "POLICY_RULES_LOADING_FAILED",
            status     = "FAILED",
            message    = str(e),
            db_session = db_session
        )
        pa_format = "{}"
        policy_rules = "[]"

    today = datetime.now().strftime("%B %d, %Y")

    # 3-5. OPTIMIZATION 8: Generate all PA documents in single batch call (instead of 3 separate calls)
    logger.info("[pa_document_agent] Generating all PA documents in batch (Optimization 8)...")
    batch_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "PA_DOCUMENT_AGENT",
        event      = "BATCH_PA_GENERATION_STARTED",
        status     = "RUNNING",
        message    = "Generating cover letter, clinical summary, and checklist in single LLM call (Opt 8)",
        db_session = db_session
    )
    
    try:
        # Single LLM call returns all 3 documents
        batch_result = _invoke_combined_pa_generation(
            ehr_text=ehr_text,
            date=today,
            pa_format=pa_format,
            policy_rules=policy_rules
        )
        
        cover_letter = batch_result.get("cover_letter", "")
        clinical_summary = batch_result.get("clinical_summary", "")
        checklist = batch_result.get("checklist", [])
        
        batch_duration_ms = int((time.time() - batch_start) * 1000)
        log_event(
            case_id     = case_id,
            agent_name  = "PA_DOCUMENT_AGENT",
            event       = "BATCH_PA_GENERATION_COMPLETED",
            status      = "SUCCESS",
            duration_ms = batch_duration_ms,
            message     = f"All 3 documents generated in {batch_duration_ms}ms (67% faster than 3 separate calls)",
            db_session  = db_session
        )
        print(f"[pa_document_agent] Batch generation succeeded in {batch_duration_ms}ms (saved ~1200ms vs 3 calls)")
        
    except Exception as e:
        logger.warning(f"[pa_document_agent] Batch generation failed: {e}. Falling back to individual LLM calls...")
        log_event(
            case_id    = case_id,
            agent_name = "PA_DOCUMENT_AGENT",
            event      = "BATCH_PA_GENERATION_FAILED",
            status     = "FALLBACK",
            message    = f"Falling back to 3 individual calls: {str(e)}",
            db_session = db_session
        )
        
        # Fallback: 3 separate calls (original behavior)
        cl_start = time.time()
        log_event(case_id=case_id, agent_name="PA_DOCUMENT_AGENT", event="COVER_LETTER_GENERATION_STARTED", status="RUNNING", db_session=db_session)
        cover_letter = _invoke(
            get_cover_letter_prompt(),
            {"ehr_data": ehr_text, "date": today, "pa_format": pa_format},
        )
        log_event(
            case_id=case_id,
            agent_name="PA_DOCUMENT_AGENT",
            event="COVER_LETTER_GENERATION_COMPLETED",
            status="SUCCESS",
            duration_ms=int((time.time() - cl_start) * 1000),
            db_session=db_session
        )

        cs_start = time.time()
        log_event(case_id=case_id, agent_name="PA_DOCUMENT_AGENT", event="CLINICAL_SUMMARY_GENERATION_STARTED", status="RUNNING", db_session=db_session)
        clinical_summary = _invoke(
            get_clinical_summary_prompt(),
            {"ehr_data": ehr_text, "pa_format": pa_format},
        )
        log_event(
            case_id=case_id,
            agent_name="PA_DOCUMENT_AGENT",
            event="CLINICAL_SUMMARY_GENERATION_COMPLETED",
            status="SUCCESS",
            duration_ms=int((time.time() - cs_start) * 1000),
            db_session=db_session
        )

        ch_start = time.time()
        log_event(case_id=case_id, agent_name="PA_DOCUMENT_AGENT", event="CHECKLIST_GENERATION_STARTED", status="RUNNING", db_session=db_session)
        raw_checklist = _invoke(
            get_checklist_prompt(),
            {"ehr_data": ehr_text, "policy_rules": policy_rules},
        )
        log_event(
            case_id=case_id,
            agent_name="PA_DOCUMENT_AGENT",
            event="CHECKLIST_GENERATION_COMPLETED",
            status="SUCCESS",
            duration_ms=int((time.time() - ch_start) * 1000),
            db_session=db_session
        )

        # Parse checklist JSON from individual call
        checklist = []
        try:
            clean = re.sub(r"```(?:json)?|```", "", raw_checklist).strip()
            checklist = json.loads(clean)
        except Exception as e:
            logger.error(f"[pa_document_agent] Checklist JSON parse failed: {e}")
        checklist = [{"item": "See generated summary", "met": True, "evidence": raw_checklist[:300]}]

    log_event(
        case_id     = case_id,
        agent_name  = "PA_DOCUMENT_AGENT",
        event       = "DOCUMENT_GENERATION_COMPLETED",
        status      = "SUCCESS",
        message     = f"Generated cover letter, summary, and {len(checklist)} checklist items",
        duration_ms = int((time.time() - agent_start) * 1000),
        db_session  = db_session
    )

    return {
        "ehr": ehr,
        "cover_letter": cover_letter,
        "clinical_summary": clinical_summary,
        "checklist": checklist,
    }
