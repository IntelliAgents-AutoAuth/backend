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
from utils.llm_util import get_keys
import time

from prompts.eligibility_prompts import get_eligibility_prompt

# ─────────────────────────────────────────
# 1. SINGLETON LLM CHAIN (direct call, no agent loop)
# ─────────────────────────────────────────

_eligibility_chain = None


def get_eligibility_chain(api_key=None):
    """Creates an eligibility chain using the provided API key (or default from env)."""
    if not api_key:
        api_key = os.getenv("GOOGLE_API_KEY")

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
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

    all_keys = get_keys()
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

        # ── 1.1 FORMAT UPLOADED EVIDENCE ─────────
        uploaded_evidence = ""
        if raw_ehr and "user_uploaded_files" in raw_ehr:
            uploads = raw_ehr["user_uploaded_files"]
            if uploads:
                uploaded_evidence = "\n### NEWLY_UPLOADED_EVIDENCE:\n"
                for i, up in enumerate(uploads, 1):
                    name = up.get("document_name") or up.get("file_path", "Unknown File")
                    text = up.get("extracted_text", "No text extracted.")
                    uploaded_evidence += f"\n--- DOCUMENT {i}: {name} ---\n{text}\n"

        log_event(
            case_id     = case_id,
            agent_name  = "ELIGIBILITY_AGENT",
            event       = "EHR_FETCH_COMPLETED",
            status      = "SUCCESS",
            message     = f"EHR data fetched. Evidence uploads: {len(raw_ehr.get('user_uploaded_files', [])) if raw_ehr else 0}",
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
        raw_ehr = None
        ehr_data = "ERROR: Failed to fetch EHR data."
        uploaded_evidence = ""

    print(f"[eligibility_agent] Sending one-shot eligibility request to LLM for {case_id}...")
    llm_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "ELIGIBILITY_AGENT",
        event      = "LLM_VERDICT_STARTED",
        status     = "RUNNING",
        message    = "Reasoning over policy and EHR"
    )

    prompt_input = {
        "input": f"""
Perform a final Policy Eligibility Check for {case_id}.

### POLICY_TEXT:
{policy_text}

### PATIENT_EHR:
{ehr_data}
{uploaded_evidence}

INSTRUCTIONS:
- Compare the PATIENT_EHR and NEWLY_UPLOADED_EVIDENCE against the POLICY_TEXT requirements.
- Determine if the case is ELIGIBLE or NOT_ELIGIBLE.
- Return a VERDICT and REASON following the strict sequence.
"""
    }

    response = None
    success = False
    
    for key_index, current_key in enumerate(all_keys):
        if success: break
        
        print(f"[eligibility_agent] Attempting LLM request with Key {key_index + 1}/{len(all_keys)}")
        
        try:
            current_chain = get_eligibility_chain(api_key=current_key)
            response = current_chain.invoke(prompt_input)
            
            print(f"[eligibility_agent] LLM verdict received (Key {key_index + 1})")
            success = True
            break
        except Exception as e:
            error_text = str(e)
            print(f"[eligibility_agent] Key {key_index + 1} failed: {error_text}")
            
            if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
                print(f"[eligibility_agent] Key {key_index + 1} exhausted. Switching next...")
                continue
            else:
                print(f"[eligibility_agent] Fatal LLM error: {error_text}")
                success = False
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

    return {
        "case_id": case_id,
        "eligible": parsed.get("eligible"),
        "verdict": parsed.get("verdict"),
        "reason": parsed.get("reason"),
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
