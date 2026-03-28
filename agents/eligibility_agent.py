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
from utils.llm_util import get_keys, get_model_order
from constants.cases import CaseStatus
import time

from prompts.eligibility_prompts import get_eligibility_prompt

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
    reason_match  = re.search(r"(?:REASONING|REASON)\s*:\s*(.*?)(?=\s*VERDICT\s*:|$)", raw_output, re.IGNORECASE | re.DOTALL)

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
    eligibility_criteria_list = "ERROR: Failed to load eligibility criteria."
    ehr_data = "ERROR: Failed to fetch EHR data."

    try:
        rules_path = os.path.join(backend_dir, "policy-pdfs", "extracted_policy_rules.json")
        pdf_start = time.time()
        log_event(
            case_id    = case_id,
            agent_name = "ELIGIBILITY_AGENT",
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
            
            crit_docs = target_data.get("eligibility_criteria", [])
            eligibility_criteria_list = json.dumps(crit_docs, indent=2)
        else:
            eligibility_criteria_list = "[]"
            
        log_event(
            case_id     = case_id,
            agent_name  = "ELIGIBILITY_AGENT",
            event       = "POLICY_RULES_LOADING_COMPLETED",
            status      = "SUCCESS",
            message     = f"Loaded eligibility criteria successfully",
            duration_ms = int((time.time() - pdf_start) * 1000)
        )
        print(f"[eligibility_agent] Eligibility criteria loaded successfully from extracted rules.")
    except Exception as e:
        log_event(
            case_id    = case_id,
            agent_name = "ELIGIBILITY_AGENT",
            event      = "POLICY_RULES_LOADING_FAILED",
            status     = "FAILED",
            message    = str(e)
        )
        print(f"[eligibility_agent] Policy Rules Loading failed: {e}")

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
        if raw_ehr:
            ehr_data = json.dumps(raw_ehr, indent=2, default=str)
            
            # --- RAG POLICY ENHANCEMENT ---
            diagnosis = raw_ehr.get("primary_diagnosis") or raw_ehr.get("diagnosis")
            if diagnosis:
                try:
                    from tools.policy_retriever import search_policy_criteria
                    rag_criteria = search_policy_criteria(doc_type="eligibility_criteria")
                    eligibility_criteria_list = f"[RAG STRUCTURED RULES]:\n{rag_criteria}"
                    print(f"[eligibility_agent] Loaded structured eligibility_criteria from ChromaDB")
                except Exception as e:
                    print(f"[eligibility_agent] RAG fetch failed (is ChromaDB built?): {e}")
        else:
            ehr_data = "No specific patient data found."

        # ── 1.1 FORMAT UPLOADED EVIDENCE ─────────
        uploaded_evidence = ""
        if raw_ehr and "user_uploaded_files" in raw_ehr:
            uploads = raw_ehr["user_uploaded_files"]
            if uploads:
                uploaded_evidence = "\n### NEWLY_UPLOADED_EVIDENCE:\n"
                for i, up in enumerate(uploads, 1):
                    name = up.get("document_name") or up.get("file_path", "Unknown File")
                    text = up.get("extracted_text", "No text extracted.")
                    uploaded_evidence += f"\n--- DATABASE RECORD: {name} ---\n{text}\n"

        # ── 1.2 READ LOCAL PDF UPLOADS ───────────
        upload_dir = os.path.join(backend_dir, "uploads", str(case_id))
        if os.path.exists(upload_dir) and os.path.isdir(upload_dir):
            try:
                from pypdf import PdfReader
                pdf_files = [f for f in os.listdir(upload_dir) if f.lower().endswith('.pdf')]
                if pdf_files:
                    if not uploaded_evidence.strip():
                        uploaded_evidence = "\n### NEWLY_UPLOADED_EVIDENCE:\n"
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
                                uploaded_evidence += f"\n--- LOCAL UPLOAD: {pdf_file} ---\n{text}\n"
                                print(f"[eligibility_agent] Local PDF read successfully: {pdf_file}")
                        except Exception as inner_e:
                            print(f"[eligibility_agent] Failed to parse local PDF {pdf_file}: {inner_e}")
            except ImportError:
                print(f"[eligibility_agent] pypdf not installed, skipping local PDF reads.")
            except Exception as e:
                print(f"[eligibility_agent] Error reading uploads folder: {e}")

        log_event(
            case_id     = case_id,
            agent_name  = "ELIGIBILITY_AGENT",
            event       = "EHR_FETCH_COMPLETED",
            status      = "SUCCESS",
            message     = f"EHR data and {len(uploaded_evidence)} bytes of evidence fetched.",
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
                db_case.status = CaseStatus.APPROVED.value
            else:
                db_case.status = CaseStatus.DENIED.value
            
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
