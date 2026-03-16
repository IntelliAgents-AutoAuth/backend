import os
import sys
import logging
import json

# Add the backend directory to sys.path to ensure local imports work
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from core.config import settings
from constants.cases import CaseStatus
from prompts.gap_analysis_prompts import get_gap_analysis_prompt
from utils.agent_logger import log_event
import time

# ─────────────────────────────────────────
# SILENCE NOISY LOGGERS
# ─────────────────────────────────────────
logging.getLogger("langchain").setLevel(logging.ERROR)
logging.getLogger("google.generativeai").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

# ─────────────────────────────────────────
# 1. ENVIRONMENT
# ─────────────────────────────────────────
load_dotenv(os.path.join(backend_dir, ".env"))

# ─────────────────────────────────────────
# LAZY SINGLETON — Direct LLM chain (no agent loop)
# ─────────────────────────────────────────
_llm_chain = None


def get_llm_chain():
    """Lazy initialization — LLM chain created once, reused for all calls."""
    global _llm_chain
    if _llm_chain is not None:
        return _llm_chain

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("[gap_analysis_agent] WARNING: GOOGLE_API_KEY is not set.")

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-lite",
        temperature=0,
        google_api_key=api_key
    )

    prompt = get_gap_analysis_prompt()
    _llm_chain = prompt | llm
    return _llm_chain


# ─────────────────────────────────────────
# 8. RUN AGENT — call this from FastAPI
# ─────────────────────────────────────────

from db.session import SessionLocal
from crud import crud_case

async def run_gap_analysis(props: dict) -> dict:
    """
    Main function — call this from FastAPI endpoint.

    Input:
      props = {
        "case_id":      str,
        "patient_name": str  (optional),
        "pdf_path":     str  (optional)
      }

    Output:
      {
        "case_id": str,
        "output":  dict (full structured JSON from LLM)
      }
    """
    case_id      = props.get("case_id")
    pdf_path     = props.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        pdf_path = os.path.join(
            backend_dir, "policy-pdfs", "aetna", "test_doc.pdf"
        )
    patient_name = props.get("patient_name", "Unknown")

    from crud import crud_case
    db = SessionLocal()

    # Prevent duplicate parallel gap analysis
    db_case = crud_case.get_case(db, case_id=case_id)
    if db_case and db_case.status == CaseStatus.GAP_ANALYSIS_RUNNING.value:
        print(f"[gap_analysis_agent] Gap analysis already running for {case_id}, skipping duplicate invocation.")
        db.close()
        return {"case_id": case_id, "output": {"status": "IN_PROGRESS", "message": "Gap analysis already running."}}

    # Mark as running
    if db_case:
        db_case.status = CaseStatus.GAP_ANALYSIS_RUNNING.value
        db.add(db_case)
        db.commit()

    db.close()

    # ── Default PDF for demo/testing ─────────
    if not pdf_path or not os.path.exists(pdf_path):
        pdf_path = os.path.join(
            backend_dir, "policy-pdfs", "aetna", "test_doc.pdf"
        )

    print(f"\n[gap_analysis_agent] Gap analysis triggered for case_id={case_id}, patient={patient_name}")
    print(f"[gap_analysis_agent] --- Started for {case_id} ---")

    agent_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "GAP_ANALYSIS_AGENT",
        event      = "GAP_ANALYSIS_STARTED",
        status     = "RUNNING",
        message    = "Gap analysis triggered"
    )

    # ── 1. PRE-EXTRACT DATA ──────────────────
    policy_text = "ERROR: Failed to extract policy."
    ehr_data = "ERROR: Failed to fetch EHR data."

    try:
        from tools.pdf_extractor import extract_raw_text
        pdf_start = time.time()
        log_event(
            case_id    = case_id,
            agent_name = "GAP_ANALYSIS_AGENT",
            event      = "PDF_EXTRACTION_STARTED",
            status     = "RUNNING"
        )
        policy_text = extract_raw_text(pdf_path)
        log_event(
            case_id     = case_id,
            agent_name  = "GAP_ANALYSIS_AGENT",
            event       = "PDF_EXTRACTION_COMPLETED",
            status      = "SUCCESS",
            message     = f"Extracted {len(policy_text)} chars",
            duration_ms = int((time.time() - pdf_start) * 1000)
        )
        print(f"[gap_analysis_agent] PDF extracted successfully from {pdf_path} ({len(policy_text)} chars)")
    except Exception as e:
        log_event(
            case_id    = case_id,
            agent_name = "GAP_ANALYSIS_AGENT",
            event      = "PDF_EXTRACTION_FAILED",
            status     = "FAILED",
            message    = str(e)
        )
        print(f"[gap_analysis_agent] PDF Extraction failed: {e}")

    try:
        from tools.ehr_fetcher import fetch_extracted_data_by_case
        ehr_start = time.time()
        log_event(
            case_id    = case_id,
            agent_name = "GAP_ANALYSIS_AGENT",
            event      = "EHR_FETCH_STARTED",
            status     = "RUNNING"
        )
        raw_ehr = fetch_extracted_data_by_case(case_id)
        # Use default=str to handle datetime/date objects
        ehr_data = json.dumps(raw_ehr, indent=2, default=str) if raw_ehr else "No specific patient data found."

        if raw_ehr is None:
            ehr_count = 0
        elif isinstance(raw_ehr, list):
            ehr_count = len(raw_ehr)
        elif isinstance(raw_ehr, dict):
            ehr_count = len(raw_ehr)
        else:
            ehr_count = 1

        log_event(
            case_id     = case_id,
            agent_name  = "GAP_ANALYSIS_AGENT",
            event       = "EHR_FETCH_COMPLETED",
            status      = "SUCCESS",
            message     = "EHR data fetched successfully",
            duration_ms = int((time.time() - ehr_start) * 1000)
        )
        print(f"[gap_analysis_agent] EHR data fetched for {case_id}; records={ehr_count}")

        if isinstance(raw_ehr, dict):
            uploaded_files = raw_ehr.get("uploaded_files") or raw_ehr.get("files") or raw_ehr.get("documents")
            if uploaded_files:
                if isinstance(uploaded_files, list):
                    print(f"[gap_analysis_agent] Bulk uploaded files detected: {len(uploaded_files)} entries")
                else:
                    print(f"[gap_analysis_agent] Uploaded files field exists: {type(uploaded_files)}")

    except Exception as e:
        log_event(
            case_id    = case_id,
            agent_name = "GAP_ANALYSIS_AGENT",
            event      = "EHR_FETCH_FAILED",
            status     = "FAILED",
            message    = str(e)
        )
        print(f"[gap_analysis_agent] EHR Fetch failed: {e}")

    # ── 2. PREPARE INPUT ─────────────────────
    agent_input = {
        "input": f"""
Perform a Gap Analysis for {case_id}.

### POLICY_TEXT:
{policy_text}

### PATIENT_EHR:
{ehr_data}

INSTRUCTIONS:
- Review the POLICY_TEXT for requirements.
- Review the PATIENT_EHR for evidence.
- Return the structured Gap Analysis JSON.
"""
    }

    # ── 3. RUN LLM ───────────────────────────
    # Direct one-shot LLM call — no agent loop, no tools, no iteration limit.
    print("[gap_analysis_agent] Sending one-shot request to LLM for gap analysis...")

    output = None
    parsed = None

    llm_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "GAP_ANALYSIS_AGENT",
        event      = "LLM_CALL_STARTED",
        status     = "RUNNING",
        message    = "Sending to Gemini for gap analysis"
    )

    for attempt in range(1, 4):
        try:
            response = await get_llm_chain().ainvoke(agent_input)
            print(f"[gap_analysis_agent] LLM response received (attempt {attempt})")
            # LangChain returns an AIMessage; get raw text content
            output = response.content if hasattr(response, "content") else str(response)
            log_event(
                case_id     = case_id,
                agent_name  = "GAP_ANALYSIS_AGENT",
                event       = "LLM_CALL_COMPLETED",
                status      = "SUCCESS",
                message     = "Gemini responded successfully",
                duration_ms = int((time.time() - llm_start) * 1000)
            )
            break
        except Exception as e:
            error_text = str(e)
            print(f"[gap_analysis_agent] LLM request failed on attempt {attempt}: {error_text}")

            # Rate-limit handling for Gemini / genai ClientError
            if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text or "Too Many Requests" in error_text:
                retry_delay = 10.0
                if "retryDelay" in error_text:
                    import re
                    match = re.search(r"([0-9]+(?:\.[0-9]+)?)s", error_text)
                    if match:
                        retry_delay = float(match.group(1))
                print(f"[gap_analysis_agent] Rate limit hit; retrying in {retry_delay}s...")
                import asyncio
                await asyncio.sleep(retry_delay)
                continue
            else:
                print(f"[gap_analysis_agent] Non-retryable LLM error: {error_text}")
                log_event(
                    case_id    = case_id,
                    agent_name = "GAP_ANALYSIS_AGENT",
                    event      = "LLM_CALL_FAILED",
                    status     = "FAILED",
                    message    = error_text
                )
                parsed = {"status": "FAILED", "message": error_text, "raw": error_text}
                break

    if output is None and parsed is None:
        parsed = {"status": "FAILED", "message": "LLM did not return output after retries", "raw": ""}

    if output is not None:
        # Strip markdown code fences if LLM wraps JSON in ```json ... ```
        clean = output.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1]  # drop opening fence line
            clean = clean.rsplit("```", 1)[0].strip()  # drop closing fence
        try:
            parsed = json.loads(clean)
        except Exception:
            parsed = {"raw": output}

    if isinstance(parsed, dict):
        summary = parsed.get("summary", {})
        total_required = summary.get("total_required")
        total_matched = summary.get("total_matched")
        total_missing = summary.get("total_missing")
        gap_pct = summary.get("gap_percentage")

        if total_required is None or total_matched is None or total_missing is None:
            print("[gap_analysis_agent] WARNING: Gap analysis summary is missing from LLM output.")

        print(f"[gap_analysis_agent] Gap result summary: total_required={total_required}, total_matched={total_matched}, total_missing={total_missing}, gap_percentage={gap_pct}")
    else:
        print("[gap_analysis_agent] WARNING: Unable to parse LLM output into dict summary.")

    print(f"[gap_analysis_agent] About to send result back to frontend for case_id={case_id}")

    # ── PERSISTENCE ──────────────────────────
    # Create a fresh DB session for the background task
    db = SessionLocal()
    try:
        db_case = crud_case.get_case(db, case_id=case_id)
        if db_case:
            summary = parsed.get("summary", {})
            db_case.gap_result = parsed

            # Keep status from LLM if valid, else once complete set to GAP_CLEARED or GAP_ANALYSIS_FAILED
            new_status = parsed.get("status")
            if new_status == "INCOMPLETE":
                db_case.status = CaseStatus.GAP_ANALYSIS_FAILED.value
            elif new_status:
                db_case.status = new_status
            else:
                # If the LLM returns a complete result but no explicit status,
                # mark as GAP_CLEARED when no missing documents are found.
                missing_docs = parsed.get("missing_documents")
                if isinstance(missing_docs, list) and len(missing_docs) == 0:
                    db_case.status = CaseStatus.GAP_CLEARED.value


            db_case.total_required = summary.get("total_required")
            db_case.total_matched  = summary.get("total_matched")
            db_case.total_missing  = summary.get("total_missing")
            db_case.gap_percentage = summary.get("gap_percentage")

            db.add(db_case)
            db.commit()
            db.refresh(db_case)

            # ── LOG 5: Final Result ──────────────────
            total_duration = int((time.time() - agent_start) * 1000)
            gap_status = parsed.get("status", "UNKNOWN")
            summary    = parsed.get("summary", {})

            log_event(
                case_id     = case_id,
                agent_name  = "GAP_ANALYSIS_AGENT",
                event       = "GAP_ANALYSIS_COMPLETED",
                status      = gap_status,
                message     = f"Missing {summary.get('total_missing', 0)} of {summary.get('total_required', 0)} documents",
                metadata    = {
                    "total_required": summary.get("total_required"),
                    "total_matched":  summary.get("total_matched"),
                    "total_missing":  summary.get("total_missing"),
                    "gap_percentage": summary.get("gap_percentage"),
                    "next_action":    parsed.get("next_action")
                },
                duration_ms = total_duration
            )
            print(f"[gap_analysis_agent] Persisted results for {case_id}")

    except Exception as e:
        print(f"[gap_analysis_agent] Persistence/Chaining failed for {case_id}: {e}")
        db.rollback()
        try:
            if db_case:
                db_case.status = CaseStatus.GAP_ANALYSIS_FAILED.value
                db.add(db_case)
                db.commit()
                log_event(
                    case_id    = case_id,
                    agent_name = "GAP_ANALYSIS_AGENT",
                    event      = "GAP_ANALYSIS_FAILED",
                    status     = "FAILED",
                    message    = str(e)
                )
        except Exception as err:
            print(f"[gap_analysis_agent] Failed to mark gap analysis failure for {case_id}: {err}")
    finally:
        db.close()

    print(f"[gap_analysis_agent] --- Completed for {case_id} ---\n")
    print("result :",parsed)
    return {
        "case_id": case_id,
        "output":  parsed
    }


# ─────────────────────────────────────────
# TEST
# ─────────────────────────────────────────

if __name__ == "__main__":
    result = run_gap_analysis({
        "case_id":      "CASE_001",
        "patient_name": "John Smith",
        "pdf_path":     None
    })
    print(result)