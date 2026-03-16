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

# Ensure backend root is on sys.path for local imports
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from utils.agent_logger import log_event
import time

from prompts.eligibility_prompts import get_eligibility_prompt

# ─────────────────────────────────────────
# 1. SINGLETON LLM CHAIN (direct call, no agent loop)
# ─────────────────────────────────────────

_eligibility_chain = None


def get_eligibility_chain():
    """Lazy singleton — only spins up the LLM once."""
    global _eligibility_chain
    if _eligibility_chain is not None:
        return _eligibility_chain

    load_dotenv(os.path.join(backend_dir, ".env"))
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("[eligibility_agent] WARNING: GOOGLE_API_KEY is not set.")

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-lite",
        temperature=0,
        google_api_key=api_key,
    )

    prompt = get_eligibility_prompt()
    _eligibility_chain = prompt | llm
    return _eligibility_chain


# ─────────────────────────────────────────
# 2. PARSE VERDICT FROM LLM OUTPUT
# ─────────────────────────────────────────

def _parse_verdict(raw_output: str) -> dict:
    """
    Parse the strict VERDICT / REASON output format from the LLM.
    Falls back gracefully if the format is not exactly followed.
    """
    verdict = "NOT_ELIGIBLE"   # safe default
    reason = raw_output.strip()

    verdict_match = re.search(r"VERDICT\s*:\s*(ELIGIBLE|NOT_ELIGIBLE)", raw_output, re.IGNORECASE)
    reason_match  = re.search(r"REASON\s*:\s*(.+)", raw_output, re.IGNORECASE | re.DOTALL)

    if verdict_match:
        verdict = verdict_match.group(1).upper()
    if reason_match:
        reason = reason_match.group(1).strip()

    return {
        "verdict": verdict,
        "eligible": verdict == "ELIGIBLE",
        "reason": reason,
    }


# ─────────────────────────────────────────
# 3. PUBLIC API — call from FastAPI
# ─────────────────────────────────────────

def run_eligibility_check(props: dict) -> dict:
    """
    Main entry point. Call this from a FastAPI endpoint.

    Input:
        props = {
            "case_id": str,           # used by ehr_fetcher to pull the EHR
            "pdf_path": str | None,   # policy PDF; defaults to aetna/test_doc.pdf
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

    # Default PDF path when none is explicitly provided
    if not pdf_path:
        pdf_path = os.path.join(
            backend_dir, "policy-pdfs", "aetna", "test_doc.pdf"
        )

    chain = get_eligibility_chain()
    agent_start = time.time()

    log_event(
        case_id    = case_id,
        agent_name = "ELIGIBILITY_AGENT",
        event      = "ELIGIBILITY_CHECK_STARTED",
        status     = "RUNNING",
        message    = "Eligibility check triggered"
    )

    # ── 1. PRE-EXTRACT DATA ──────────────────
    policy_text = "ERROR: Failed to extract policy."
    ehr_data = "ERROR: Failed to fetch EHR data."

    try:
        from tools.pdf_extractor import extract_raw_text
        pdf_start = time.time()
        log_event(
            case_id    = case_id,
            agent_name = "ELIGIBILITY_AGENT",
            event      = "PDF_EXTRACTION_STARTED",
            status     = "RUNNING"
        )
        policy_text = extract_raw_text(pdf_path)
        log_event(
            case_id     = case_id,
            agent_name  = "ELIGIBILITY_AGENT",
            event       = "PDF_EXTRACTION_COMPLETED",
            status      = "SUCCESS",
            message     = f"Extracted {len(policy_text)} chars",
            duration_ms = int((time.time() - pdf_start) * 1000)
        )
    except Exception as e:
        log_event(
            case_id    = case_id,
            agent_name = "ELIGIBILITY_AGENT",
            event      = "PDF_EXTRACTION_FAILED",
            status     = "FAILED",
            message    = str(e)
        )
        print(f"[eligibility_agent] PDF Extraction failed: {e}")

    try:
        from tools.ehr_fetcher import fetch_extracted_data_by_case
        ehr_start = time.time()
        log_event(
            case_id    = case_id,
            agent_name = "ELIGIBILITY_AGENT",
            event      = "EHR_FETCH_STARTED",
            status     = "RUNNING"
        )
        raw_ehr = fetch_extracted_data_by_case(case_id)
        ehr_data = json.dumps(raw_ehr, indent=2, default=str) if raw_ehr else "No specific patient data found."
        log_event(
            case_id     = case_id,
            agent_name  = "ELIGIBILITY_AGENT",
            event       = "EHR_FETCH_COMPLETED",
            status      = "SUCCESS",
            message     = "EHR data fetched successfully",
            duration_ms = int((time.time() - ehr_start) * 1000)
        )
    except Exception as e:
        log_event(
            case_id    = case_id,
            agent_name = "ELIGIBILITY_AGENT",
            event      = "EHR_FETCH_FAILED",
            status     = "FAILED",
            message    = str(e)
        )
        print(f"[eligibility_agent] EHR Fetch failed: {e}")

    print(f"[eligibility_agent] Sending one-shot eligibility request to LLM for {case_id}...")
    llm_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "ELIGIBILITY_AGENT",
        event      = "LLM_VERDICT_STARTED",
        status     = "RUNNING",
        message    = "Reasoning over policy and EHR"
    )

    response = chain.invoke({
        "input": f"""
Perform a final Policy Eligibility Check for {case_id}.

### POLICY_TEXT:
{policy_text}

### PATIENT_EHR:
{ehr_data}

INSTRUCTIONS:
- Compare the PATIENT_EHR evidence against the POLICY_TEXT requirements.
- Determine if the case is ELIGIBLE or NOT_ELIGIBLE.
- Return a VERDICT and REASON following the strict sequence.
"""
    })
    
    log_event(
        case_id     = case_id,
        agent_name  = "ELIGIBILITY_AGENT",
        event       = "LLM_VERDICT_COMPLETED",
        status      = "SUCCESS",
        message     = "Eligibility verdict received",
        duration_ms = int((time.time() - llm_start) * 1000)
    )

    raw_output = response.content if hasattr(response, "content") else str(response)
    parsed     = _parse_verdict(raw_output)

    # ── PERSISTENCE ──────────────────────────
    from db.session import SessionLocal
    from crud import crud_case
    db = SessionLocal()
    try:
        db_case = crud_case.get_case(db, case_id=case_id)
        if db_case:
            db_case.eligibility_result = parsed
            db_case.eligibility_verdict = parsed.get("verdict")
            # If eligible, we can move the status forward
            if parsed.get("eligible"):
                db_case.status = "APPROVED"
            else:
                db_case.status = "DENIED"
            
            db.add(db_case)
            db.commit()
            db.refresh(db_case)
            
            total_duration = int((time.time() - agent_start) * 1000)
            log_event(
                case_id     = case_id,
                agent_name  = "ELIGIBILITY_AGENT",
                event       = "ELIGIBILITY_CHECK_COMPLETED",
                status      = parsed.get("verdict"),
                message     = parsed.get("reason")[:200] + "..." if len(parsed.get("reason", "")) > 200 else parsed.get("reason"),
                metadata    = parsed,
                duration_ms = total_duration
            )
            print(f"[eligibility_agent] Persisted results for {case_id}")
    except Exception as e:
        print(f"[eligibility_agent] Persistence failed for {case_id}: {e}")
        db.rollback()
    finally:
        db.close()

    # ── AUTO-CHAINING ────────────────────────
    # Trigger document generation ONLY if approved
    if parsed.get("eligible"):
        print(f"[eligibility_agent] SUCCESS: Case {case_id} is eligible. Triggering Document Generation...")
        from agents.pa_document_agent import generate_pa_content
        try:
            generate_pa_content(case_id=case_id, pdf_path=pdf_path)
        except Exception as doc_err:
            print(f"[eligibility_agent] Auto-chaining Document Agent failed: {doc_err}")

    return {
        "case_id": case_id,
        **parsed,
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
