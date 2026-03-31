import os
import sys
import logging
import json
import asyncio

# Add the backend directory to sys.path to ensure local imports work
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from utils.llm_util import get_keys

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


def get_llm_chain(api_key=None):
    """Creates an LLM chain using the provided API key (or default from env)."""
    if not api_key:
        api_key = os.getenv("GOOGLE_API_KEY")
    
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0,
        google_api_key=api_key
    )

    prompt = get_gap_analysis_prompt()
    return prompt | llm


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

    # Prevent duplicate parallel gap analysis if NOT already set by a trusted caller (like Orchestrator)
    # Actually, if it's already RUNNING, we only skip if it's a truly redundant parallel request.
    # For now, we'll allow it to proceed if the status is already RUNNING to avoid the Orchestrator lock.
    db_case = crud_case.get_case(db, case_id=case_id)
    # Removed strict block to allow Orchestrator-led flow

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
    required_docs_list = "ERROR: Failed to load required documents."
    ehr_data = "ERROR: Failed to fetch EHR data."

    try:
        rules_path = os.path.join(backend_dir, "policy-pdfs", "extracted_policy_rules.json")
        pdf_start = time.time()
        log_event(
            case_id    = case_id,
            agent_name = "GAP_ANALYSIS_AGENT",
            event      = "POLICY_RULES_LOADING_STARTED",
            status     = "RUNNING"
        )
        
        with open(rules_path, 'r', encoding='utf-8') as f:
            rules_data = json.load(f)
            
        if isinstance(rules_data, list) and len(rules_data) > 0:
            target_data = rules_data[0].get("extracted_data", {})
            for item in rules_data:
                if item.get("file") == os.path.basename(pdf_path):
                    target_data = item.get("extracted_data", {})
                    break
            
            req_docs = target_data.get("required_documents", [])
            required_docs_list = json.dumps(req_docs, indent=2)
        else:
            required_docs_list = "[]"
            
        log_event(
            case_id     = case_id,
            agent_name  = "GAP_ANALYSIS_AGENT",
            event       = "POLICY_RULES_LOADING_COMPLETED",
            status      = "SUCCESS",
            message     = f"Loaded required documents list successfully",
            duration_ms = int((time.time() - pdf_start) * 1000)
        )
        print(f"[gap_analysis_agent] Required docs list loaded successfully from extracted rules.")
    except Exception as e:
        log_event(
            case_id    = case_id,
            agent_name = "GAP_ANALYSIS_AGENT",
            event      = "POLICY_RULES_LOADING_FAILED",
            status     = "FAILED",
            message    = str(e)
        )
        print(f"[gap_analysis_agent] Policy Rules Loading failed: {e}")

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
    uploaded_evidence = ""
    if raw_ehr and isinstance(raw_ehr, dict):
        uploads = raw_ehr.get("user_uploaded_files")
        if uploads:
            uploaded_evidence = "\n### NEWLY_UPLOADED_EVIDENCE:\n"
            for i, up in enumerate(uploads, 1):
                name = up.get("document_name") or up.get("file_path", "Unknown File")
                text = up.get("extracted_text", "No text extracted.")
                uploaded_evidence += f"\n--- DOCUMENT {i}: {name} ---\n{text}\n"

    agent_input = {
        "input": f"""
Perform a Gap Analysis for {case_id}.

### REQUIRED_DOCUMENTS_LIST:
{required_docs_list}

### PATIENT_EHR:
{ehr_data}
{uploaded_evidence}

INSTRUCTIONS:
- Review the REQUIRED_DOCUMENTS_LIST for requirements.
- Review the PATIENT_EHR and NEWLY_UPLOADED_EVIDENCE for evidence.
- Return the structured Gap Analysis JSON.
"""
    }

    # ── 3. RUN LLM ───────────────────────────
    # Direct one-shot LLM call — no agent loop, no tools, no iteration limit.
    all_keys = get_keys()
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

    success = False
    for key_index, current_key in enumerate(all_keys):
        if success: break
        
        print(f"[gap_analysis_agent] Attempting LLM request with Key {key_index + 1}/{len(all_keys)}")
        
        try:
            # Create a fresh chain with the current key
            chain = get_llm_chain(api_key=current_key)
            response = await chain.ainvoke(agent_input)
            
            print(f"[gap_analysis_agent] LLM response received (Key {key_index + 1})")
            output = response.content if hasattr(response, "content") else str(response)
            
            log_event(
                case_id     = case_id,
                agent_name  = "GAP_ANALYSIS_AGENT",
                event       = "LLM_CALL_COMPLETED",
                status      = "SUCCESS",
                message     = f"Gemini responded successfully using Key {key_index + 1}",
                duration_ms = int((time.time() - llm_start) * 1000)
            )
            success = True
            break
        except Exception as e:
            error_text = str(e)
            print(f"[gap_analysis_agent] Key {key_index + 1} failed: {error_text}")

            if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
                print(f"[gap_analysis_agent] Key {key_index + 1} exhausted. Switching to next key...")
                continue # Immediately try next key
            else:
                # Non-retryable error
                print(f"[gap_analysis_agent] Fatal LLM error: {error_text}")
                success = False
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