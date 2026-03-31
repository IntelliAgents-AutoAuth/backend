"""
Policy Eligibility Agent

Determines whether a patient is eligible for a policy claim by:
1. Fetching the full EHR record and policy PDF (pre-extracted)
2. LLM directly reasons over the data in a single call
3. LLM produces ELIGIBLE / NOT_ELIGIBLE verdict with reasoning
"""

import os
import re
import sys
import json
import logging

# Ensure backend root is on sys.path for local imports
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from utils.agent_logger import log_event
from utils.llm_util import get_keys, get_model_order
from constants.cases import CaseStatus
import time

from prompts.eligibility_prompts import get_eligibility_prompt

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# 1. SINGLETON LLM CHAIN (direct call, no agent loop)
# ─────────────────────────────────────────

_eligibility_chain = None


def get_eligibility_chain(api_key=None, model_name: str | None = None):
    """Creates an eligibility chain using the provided API key (or default from env)."""
    if not api_key:
        api_key = os.getenv("GOOGLE_API_KEY")
    if not model_name:
        model_name = get_model_order("eligibility")[0]

    llm = ChatGoogleGenerativeAI(
        model=model_name,
        temperature=0,
        google_api_key=api_key,
    )

    prompt = get_eligibility_prompt()
    return prompt | llm


# ─────────────────────────────────────────
# 2. PARSE VERDICT FROM LLM OUTPUT
# ─────────────────────────────────────────

def _parse_verdict(raw_output: str) -> dict:
    """
    Parse the strict REASONING / VERDICT output format from the LLM.
    Falls back gracefully if the format is not exactly followed.
    """
    verdict = "NOT_ELIGIBLE"   # safe default
    reason = raw_output.strip()

    verdict_match = re.search(r"VERDICT\s*:\s*(ELIGIBLE|NOT_ELIGIBLE)", raw_output, re.IGNORECASE)
    reason_match  = re.search(r"(?:REASONING|REASON)\s*:\s*(.*?)(?=\s*VERDICT\s*:\s*|PROBABILITY_OF_APPROVAL\s*:|$)", raw_output, re.IGNORECASE | re.DOTALL)
    prob_match    = re.search(r"PROBABILITY_OF_APPROVAL\s*:\s*(\d{1,3})", raw_output, re.IGNORECASE)

    if verdict_match:
        verdict = verdict_match.group(1).upper()
    if reason_match:
        reason = reason_match.group(1).strip()
    
    probability_score = 0
    if prob_match:
        try:
            probability_score = float(prob_match.group(1))
        except:
            probability_score = 0

    return {
        "verdict": verdict,
        "eligible": verdict == "ELIGIBLE",
        "reason": reason,
        "probability_score": probability_score,
    }


# ─────────────────────────────────────────
# 3. PUBLIC API — call from FastAPI
# ─────────────────────────────────────────

def run_eligibility_check(props: dict, db_session=None) -> dict:
    """
    Main entry point. Call this from a FastAPI endpoint.

    Input:
        props = {
            "case_id": str,                      # used by ehr_fetcher to pull the EHR
            "payer_name": str | None,            # Insurance payer (Aetna, Cigna, etc.)
            "pdf_path": str | None,              # policy PDF; optional
        }

    Output:
        {
            "case_id":  str,
            "eligible": bool,
            "verdict":  "ELIGIBLE" | "NOT_ELIGIBLE",
            "reason":   str,
        }
    """
    case_id  = props.get("case_id")
    pdf_path = props.get("pdf_path")
    payer_name = props.get("payer_name")
    cpt_code = None

    all_keys = get_keys()
    agent_start = time.time()

    log_event(
        case_id    = case_id,
        agent_name = "ELIGIBILITY_AGENT",
        event      = "ELIGIBILITY_CHECK_STARTED",
        status     = "RUNNING",
        message    = f"Eligibility check triggered (payer={payer_name})",
        db_session = db_session
    )

    # ── 1. PRE-EXTRACT DATA ──────────────────
    eligibility_criteria_list = "ERROR: Failed to load eligibility criteria."
    ehr_data = "ERROR: Failed to fetch EHR data."
    uploaded_evidence = ""  # Initialize to prevent UnboundLocalError (Opt 4 fix)

    try:
        from tools.ehr_fetcher import fetch_extracted_data_by_case
        
        # OPTIMIZATION 7: Try to get EHR from orchestrator memory cache first
        ehr_from_cache = props.get("ehr_data_cached")
        ehr_start = time.time()
        
        if ehr_from_cache:
            log_event(
                case_id    = case_id,
                agent_name = "ELIGIBILITY_AGENT",
                event      = "EHR_CACHE_HIT",
                status     = "SUCCESS",
                db_session = db_session
            )
            raw_ehr = ehr_from_cache
            logger.info(f"[eligibility_agent] Using cached EHR data from memory for {case_id}")
            print(f"[eligibility_agent] Using cached EHR data from memory (no fetch needed)")
        else:
            log_event(
                case_id    = case_id,
                agent_name = "ELIGIBILITY_AGENT",
                event      = "EHR_FETCH_STARTED",
                status     = "RUNNING",
                db_session = db_session
            )
            raw_ehr = fetch_extracted_data_by_case(case_id)
            logger.info(f"[eligibility_agent] Fetched fresh EHR data for {case_id}")
            print(f"[eligibility_agent] Fetched fresh EHR data (cache miss)")
        
        if raw_ehr:
            ehr_data = json.dumps(raw_ehr, indent=2, default=str)
            
            # Extract payer from EHR if not provided
            if not payer_name:
                payer_name = raw_ehr.get("payer_name") or raw_ehr.get("insurance_company")
            
            # Resolve CPT from multiple sources
            from crud import crud_case
            from db.session import SessionLocal
            db_case = crud_case.get_case(SessionLocal(), case_id=case_id)
            if db_case and db_case.cpt_code:
                cpt_code = db_case.cpt_code
            elif raw_ehr:
                cpt_code = raw_ehr.get("cpt_code")

            # Load policy criteria with payer filtering
            try:
                from tools.policy_retriever import search_policy_criteria
                rag_criteria = search_policy_criteria(doc_type="eligibility_criteria", payer=payer_name, cpt=cpt_code)
                eligibility_criteria_list = f"[RAG STRUCTURED RULES]:\n{rag_criteria}"
                logger.info(f"[eligibility_agent] Loaded eligibility_criteria for {payer_name}")
                print(f"[eligibility_agent] Loaded structured eligibility_criteria from RAG for {payer_name}")
            except ValueError as e:
                logger.warning(f"[eligibility_agent] Policy data unavailable for {payer_name}: {e}. Using default criteria.")
                print(f"[eligibility_agent] RAG fetch failed: {e}")
                eligibility_criteria_list = "[]"
            except Exception as e:
                logger.error(f"[eligibility_agent] Unexpected RAG error: {e}")
                print(f"[eligibility_agent] Unexpected RAG error: {e}")
                eligibility_criteria_list = "[]"
        else:
            ehr_data = "No specific patient data found."
            logger.warning(f"[eligibility_agent] No EHR data found for case {case_id}")
            eligibility_criteria_list = "[]"
        
        log_event(
            case_id     = case_id,
            agent_name  = "ELIGIBILITY_AGENT",
            event       = "EHR_FETCH_COMPLETED",
            status      = "SUCCESS",
            message     = f"EHR and policy data loaded for {payer_name}",
            duration_ms = int((time.time() - ehr_start) * 1000),
            db_session  = db_session
        )
    except Exception as e:
        log_event(
            case_id    = case_id,
            agent_name = "ELIGIBILITY_AGENT",
            event      = "EHR_FETCH_FAILED",
            status     = "FAILED",
            message    = str(e),
            db_session = db_session
        )
        logger.error(f"[eligibility_agent] EHR Fetch failed primary path: {e}")
        raw_ehr = None
        ehr_data = "ERROR: Failed to fetch EHR data."

    # ── 1.1 FORMAT UPLOADED EVIDENCE (DISTILLED SUMMARIES PRIORITY) ─────────
    uploaded_evidence = ""
    try:
        # 1. PRIORITY: Look for pre-calculated parallel summaries (N-parallel request logic)
        summary_file = os.path.join(backend_dir, "uploads", f"{case_id}_summaries.json")
        if os.path.exists(summary_file):
            try:
                with open(summary_file, 'r', encoding='utf-8') as f:
                    summaries = json.load(f)
                if summaries:
                    uploaded_evidence = "\n### CLINICAL_DOCUMENT_SUMMARIES (Distilled Facts):\n"
                    for i, item in enumerate(summaries, 1):
                        file_name = item.get("file", "Unknown File")
                        summary = item.get("summary", "No summary available.")
                        uploaded_evidence += f"\n--- DOCUMENT {i}: {file_name} ---\n{summary}\n"
                    print(f"[eligibility_agent] Successfully loaded {len(summaries)} parallel summaries.")
            except Exception as e:
                logger.warning(f"[eligibility_agent] Failed to read summaries file: {e}")

        # 2. FALLBACK: Direct from database record (Raw Extracted Text)
        if not uploaded_evidence.strip() and raw_ehr and "user_uploaded_files" in raw_ehr:
            uploads = raw_ehr["user_uploaded_files"]
            if uploads:
                uploaded_evidence = "\n### NEWLY_UPLOADED_EVIDENCE (Raw Extraction):\n"
                for i, up in enumerate(uploads, 1):
                    name = up.get("document_name") or up.get("file_path", "Unknown File")
                    text = up.get("extracted_text", "No text extracted.")
                    uploaded_evidence += f"\n--- DOCUMENT: {name} ---\n{text}\n"

        # 3. SAFETY: Direct from local disk (Raw PDF Parsing)
        if not uploaded_evidence.strip():
            upload_dir = os.path.join(backend_dir, "uploads", str(case_id))
            if os.path.exists(upload_dir) and os.path.isdir(upload_dir):
                from pypdf import PdfReader
                pdf_files = [f for f in os.listdir(upload_dir) if f.lower().endswith('.pdf')]
                if pdf_files:
                    uploaded_evidence = "\n### NEWLY_UPLOADED_EVIDENCE (Local disk fallback):\n"
                    for pdf_file in pdf_files:
                        pdf_path_full = os.path.join(upload_dir, pdf_file)
                        try:
                            reader = PdfReader(pdf_path_full)
                            text = ""
                            for page in reader.pages:
                                extracted = page.extract_text()
                                if extracted:
                                    text += extracted + "\n"
                            if text.strip():
                                uploaded_evidence += f"\n--- PDF FILE: {pdf_file} ---\n{text}\n"
                        except Exception as inner_e:
                            logger.warning(f"[eligibility_agent] Could not read local PDF {pdf_file}: {inner_e}")

    except Exception as e:
        logger.error(f"[eligibility_agent] Error processing uploaded evidence: {e}")

    print(f"[eligibility_agent] Sending one-shot eligibility request to LLM for {case_id}...")
    llm_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "ELIGIBILITY_AGENT",
        event      = "LLM_VERDICT_STARTED",
        status     = "RUNNING",
        message    = "Reasoning over policy and EHR",
        db_session = db_session
    )

    prompt_input = {
        "input": f"""
Perform a final Policy Eligibility Check for {case_id}.

### ELIGIBILITY_CRITERIA:
{eligibility_criteria_list}

### PATIENT_EHR:
{ehr_data}
{uploaded_evidence}

INSTRUCTIONS:
- Compare the PATIENT_EHR and NEWLY_UPLOADED_EVIDENCE against the ELIGIBILITY_CRITERIA rules.

- Determine if the case is ELIGIBLE or NOT_ELIGIBLE.
- Return a VERDICT and REASON following the strict sequence.
"""
    }

    response = None
    model_order = get_model_order("eligibility")
    for key_index, current_key in enumerate(all_keys):
        print(f"[eligibility_agent] Trying key {key_index + 1}/{len(all_keys)}")
        for model_name in model_order:
            print(f"[eligibility_agent] Attempting LLM request with key={key_index + 1}/{len(all_keys)}, model={model_name}")
            try:
                current_chain = get_eligibility_chain(api_key=current_key, model_name=model_name)
                response = current_chain.invoke(prompt_input)
                print(f"[eligibility_agent] LLM verdict received (model={model_name}, key={key_index + 1})")
                break
            except Exception as e:
                error_text = str(e)
                print(f"[eligibility_agent] model={model_name}, key={key_index + 1} failed: {error_text}")
                if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
                    print(f"[eligibility_agent] model={model_name} exhausted on key {key_index + 1}. Trying next model on same key...")
                    continue
                # Non-quota errors still try next model on the same key first.
                continue
        if response is not None:
            break
                    
    if not response:
        # Fallback if everything failed
        return {
            "case_id": case_id,
            "verdict": "NOT_ELIGIBLE",
            "eligible": False,
            "reason": "Eligibility check failed: API Quota exhausted or LLM error.",
        }
    
    log_event(
        case_id     = case_id,
        agent_name  = "ELIGIBILITY_AGENT",
        event       = "LLM_VERDICT_COMPLETED",
        status      = "SUCCESS",
        message     = "Eligibility verdict received",
        duration_ms = int((time.time() - llm_start) * 1000),
        db_session  = db_session
    )

    raw_output = response.content if hasattr(response, "content") else str(response)
    parsed     = _parse_verdict(raw_output)

    # ── PERSISTENCE ──────────────────────────
    print(f"[eligibility_agent] About to return result for case_id={case_id}")

    return {
        "case_id": case_id,
        "eligible": parsed.get("eligible"),
        "verdict": parsed.get("verdict"),
        "reason": parsed.get("reason"),
        "probability_score": parsed.get("probability_score", 0),
    }


# ─────────────────────────────────────────
# 4. QUICK STANDALONE TEST
# ─────────────────────────────────────────

if __name__ == "__main__":
    result = run_eligibility_check({
        "case_id":  "PA-20260309-00002",
        "pdf_path": None,
    })
    print(result)
