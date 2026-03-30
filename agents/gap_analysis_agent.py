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
from utils.llm_util import get_keys, get_model_order

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

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# LAZY SINGLETON — Direct LLM chain (no agent loop)
# ─────────────────────────────────────────
_llm_chain = None


def get_llm_chain(api_key=None, model_name: str | None = None):
    """Creates an LLM chain using the provided API key (or default from env)."""
    if not api_key:
        api_key = os.getenv("GOOGLE_API_KEY")
    if not model_name:
        model_name = get_model_order("gap_analysis")[0]
    
    llm = ChatGoogleGenerativeAI(
        model=model_name,
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
    payer_name   = props.get("payer_name")
    patient_name = props.get("patient_name", "Unknown")

    from crud import crud_case
    print(f"\n[gap_analysis_agent] Gap analysis triggered for case_id={case_id}, patient={patient_name}, payer={payer_name}")
    print(f"[gap_analysis_agent] --- Started for {case_id} ---")

    agent_start = time.time()
    log_event(
        case_id    = case_id,
        agent_name = "GAP_ANALYSIS_AGENT",
        event      = "GAP_ANALYSIS_STARTED",
        status     = "RUNNING",
        message    = f"Gap analysis triggered for {payer_name}"
    )

    # ── 1. PRE-EXTRACT DATA ──────────────────
    required_docs_list = "ERROR: Failed to load required documents."
    ehr_data = "ERROR: Failed to fetch EHR data."

    try:
        from tools.policy_retriever import search_policy_criteria
        
        # Try to get payer from case if not provided
        if not payer_name:
            try:
                db_case = crud_case.get_case(SessionLocal(), case_id=case_id)
                if db_case:
                    payer_name = db_case.insurance_company
            except Exception:
                pass
        
        # Load required documents with payer filtering
        try:
            required_docs_list = search_policy_criteria(doc_type="required_documents", payer=payer_name)
            log_event(
                case_id    = case_id,
                agent_name = "GAP_ANALYSIS_AGENT",
                event      = "POLICY_DATA_LOADED",
                status     = "SUCCESS",
                message    = f"Required documents loaded for {payer_name} from RAG"
            )
            print(f"[gap_analysis_agent] Policy documents loaded for {payer_name}")
        except ValueError as e:
            logger.warning(f"[gap_analysis_agent] Policy data unavailable for {payer_name}: {e}. Using empty list.")
            print(f"[gap_analysis_agent] Policy data unavailable: {e}")
            required_docs_list = "[]"
        except Exception as inner_e:
            logger.error(f"[gap_analysis_agent] Unexpected RAG error: {inner_e}")
            print(f"[gap_analysis_agent] RAG fetch failed: {inner_e}")
            required_docs_list = "[]"
    except Exception as e:
        log_event(
            case_id    = case_id,
            agent_name = "GAP_ANALYSIS_AGENT",
            event      = "POLICY_RULES_LOADING_FAILED",
            status     = "FAILED",
            message    = str(e)
        )
        print(f"[gap_analysis_agent] Policy loading failed: {e}")
        logger.error(f"[gap_analysis_agent] Policy loading failed: {e}")
        required_docs_list = "[]"
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

    model_order = get_model_order("gap_analysis")
    for key_index, current_key in enumerate(all_keys):
        print(f"[gap_analysis_agent] Trying key {key_index + 1}/{len(all_keys)}")
        for model_name in model_order:
            print(f"[gap_analysis_agent] Attempting LLM request with key={key_index + 1}/{len(all_keys)}, model={model_name}")
            try:
                # Create a fresh chain with the current key/model
                chain = get_llm_chain(api_key=current_key, model_name=model_name)
                response = await chain.ainvoke(agent_input)

                print(f"[gap_analysis_agent] LLM response received (model={model_name}, key={key_index + 1})")
                output = response.content if hasattr(response, "content") else str(response)

                log_event(
                    case_id     = case_id,
                    agent_name  = "GAP_ANALYSIS_AGENT",
                    event       = "LLM_CALL_COMPLETED",
                    status      = "SUCCESS",
                    message     = f"Gemini responded successfully using model={model_name}, key={key_index + 1}",
                    duration_ms = int((time.time() - llm_start) * 1000)
                )
                break
            except Exception as e:
                error_text = str(e)
                print(f"[gap_analysis_agent] model={model_name}, key={key_index + 1} failed: {error_text}")
                if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
                    print(f"[gap_analysis_agent] model={model_name} exhausted on key {key_index + 1}. Trying next model on same key...")
                    continue
                continue
        if output is not None:
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

    print(f"[gap_analysis_agent] About to return result for case_id={case_id}")

    return {
        "case_id": case_id,
        "output":  parsed
    }


# ─────────────────────────────────────────
# OPTIMIZATION 4: Delta Gap Analysis
# Lightweight re-analysis for file uploads
# ─────────────────────────────────────────

def _extract_doc_keys(doc_name: str) -> set[str]:
    """
    Extract matching keywords from document name for fuzzy matching.
    Example: "Surgical Notes Report" → {"surgical", "notes", "report"}
    """
    if not isinstance(doc_name, str):
        return set()
    return {word.lower().strip() for word in doc_name.split() if len(word) > 2}


def _covers_gap(missing_doc: dict, uploaded_files: list) -> bool:
    """
    Check if any uploaded file likely covers the missing document.
    Uses fuzzy keyword matching.
    
    Args:
        missing_doc: {"document_name": str, "document_key": str, ...}
        uploaded_files: List of {"document_name": str, "missing_key": str, "file_path": str, ...}
    
    Returns:
        True if uploaded file likely covers this gap
    """
    if not uploaded_files or not isinstance(uploaded_files, list):
        return False
    
    missing_name = missing_doc.get("document_name", "").lower()
    missing_key = missing_doc.get("document_key", "").lower()
    
    missing_keywords = _extract_doc_keys(missing_name) | _extract_doc_keys(missing_key)
    
    for uploaded in uploaded_files:
        uploaded_name = uploaded.get("document_name", "").lower()
        uploaded_key = uploaded.get("missing_key", "").lower()
        
        uploaded_keywords = _extract_doc_keys(uploaded_name) | _extract_doc_keys(uploaded_key)
        
        # Check overlap: if 50%+ of missing keywords match uploaded, consider it covered
        if missing_keywords and uploaded_keywords:
            overlap = len(missing_keywords & uploaded_keywords)
            coverage = overlap / len(missing_keywords)
            if coverage >= 0.5:
                return True
    
    return False


async def run_gap_analysis_delta(props: dict) -> dict:
    """
    OPTIMIZATION 4: Lightweight gap analysis for file uploads.
    
    Instead of re-running full LLM analysis, this:
    1. Compares newly uploaded files vs previously identified gaps
    2. Performs quick keyword matching (no LLM needed for obvious matches)
    3. Only calls LLM if complex matching is needed
    4. Returns incremental update instead of full re-analysis
    
    Args:
        props = {
            "case_id": str,
            "previous_gap_result": dict (from prior gap_analysis),
            "newly_uploaded_files": list of new uploads,
            "payer_name": str (optional)
        }
    
    Returns:
        dict with updated gap analysis
    """
    case_id = props.get("case_id")
    previous_gaps = props.get("previous_gap_result", {}) or {}
    newly_uploaded = props.get("newly_uploaded_files", []) or []
    payer_name = props.get("payer_name")
    
    logger.info(f"[gap_analysis_agent] Delta analysis for {case_id}: {len(newly_uploaded)} new files")
    log_event(
        case_id=case_id,
        agent_name="GAP_ANALYSIS_AGENT",
        event="DELTA_ANALYSIS_STARTED",
        status="RUNNING",
        message=f"Delta gap analysis for {len(newly_uploaded)} uploaded files"
    )
    
    # Extract previous missing documents
    missing_docs = previous_gaps.get("missing_documents", [])
    
    if not missing_docs:
        # No previous gaps - analysis already cleared
        logger.info(f"[gap_analysis_agent] No previous gaps for {case_id}, returning cleared status")
        return {
            "case_id": case_id,
            "output": {
                "status": "GAP_CLEARED",
                "summary": {
                    "total_required": previous_gaps.get("summary", {}).get("total_required", 0),
                    "total_matched": previous_gaps.get("summary", {}).get("total_required", 0),
                    "total_missing": 0,
                    "gap_percentage": 0
                },
                "missing_documents": [],
                "matched_documents": previous_gaps.get("matched_documents", []),
                "reason": "Delta analysis: no gaps to cover"
            }
        }
    
    # Quick check: do new files cover ALL gaps?
    remaining_gaps = []
    newly_matched = []
    
    for gap in missing_docs:
        if _covers_gap(gap, newly_uploaded):
            newly_matched.append(gap)
            logger.info(f"[gap_analysis_agent] Gap '{gap.get('document_name')}' covered by uploads")
        else:
            remaining_gaps.append(gap)
    
    # Determine status
    if not remaining_gaps:
        # All gaps satisfied!
        logger.info(f"[gap_analysis_agent] Delta analysis complete: ALL GAPS CLEARED")
        log_event(
            case_id=case_id,
            agent_name="GAP_ANALYSIS_AGENT",
            event="DELTA_ANALYSIS_COMPLETED",
            status="SUCCESS",
            message=f"Delta analysis: {len(newly_matched)} gaps covered"
        )
        
        return {
            "case_id": case_id,
            "output": {
                "status": "GAP_CLEARED",
                "summary": {
                    "total_required": previous_gaps.get("summary", {}).get("total_required", 0),
                    "total_matched": previous_gaps.get("summary", {}).get("total_required", 0),
                    "total_missing": 0,
                    "gap_percentage": 0
                },
                "missing_documents": [],
                "matched_documents": previous_gaps.get("matched_documents", []) + newly_matched,
                "reason": "Delta analysis: all gaps cleared by uploads"
            }
        }
    else:
        # Some gaps remain
        logger.info(f"[gap_analysis_agent] Delta analysis: {len(remaining_gaps)} gaps remain")
        log_event(
            case_id=case_id,
            agent_name="GAP_ANALYSIS_AGENT",
            event="DELTA_ANALYSIS_COMPLETED",
            status="SUCCESS",
            message=f"Delta analysis: {len(remaining_gaps)} gaps remain"
        )
        
        return {
            "case_id": case_id,
            "output": {
                "status": "GAP_FOUND",
                "summary": {
                    "total_required": previous_gaps.get("summary", {}).get("total_required", 0),
                    "total_matched": len(newly_matched) + len(previous_gaps.get("matched_documents", [])),
                    "total_missing": len(remaining_gaps),
                    "gap_percentage": round((len(remaining_gaps) / max(previous_gaps.get("summary", {}).get("total_required", 1), 1)) * 100, 1)
                },
                "missing_documents": remaining_gaps,
                "matched_documents": previous_gaps.get("matched_documents", []) + newly_matched,
                "reason": "Delta analysis: some gaps remain"
            }
        }


# ─────────────────────────────────────────
# TEST
# ─────────────────────────────────────────

if __name__ == "__main__":
    result = asyncio.run(run_gap_analysis({
        "case_id":      "CASE_001",
        "patient_name": "John Smith",
        "pdf_path":     None
    }))
    print(result)