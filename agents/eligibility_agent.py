"""
Policy Eligibility Agent

Determines whether a patient is eligible for a policy claim by:
1. Fetching the full EHR record via ehr_fetcher
2. Extracting policy requirements from a PDF via pdf_extractor
3. LLM directly reasons over the EHR data vs. policy requirements
4. LLM produces ELIGIBLE / NOT_ELIGIBLE verdict with reasoning
"""

import os
import re
import sys

# Ensure backend root is on sys.path for local imports
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_classic.agents import AgentExecutor, create_structured_chat_agent
from langchain_classic.memory import ConversationBufferMemory

from prompts.eligibility_prompts import get_eligibility_prompt
from tools.ehr_fetcher import ehr_fetcher
from tools.pdf_extractor import pdf_extractor

# ─────────────────────────────────────────
# 1. SINGLETON AGENT EXECUTOR
# ─────────────────────────────────────────

_eligibility_executor = None


def get_eligibility_executor():
    """Lazy singleton — only spins up the LLM once."""
    global _eligibility_executor
    if _eligibility_executor is not None:
        return _eligibility_executor

    load_dotenv(os.path.join(backend_dir, ".env"))
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("[eligibility_agent] WARNING: GOOGLE_API_KEY is not set.")

    # LLM
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-lite",
        temperature=0,
        google_api_key=api_key,
    )

    # Memory (fresh per-call is fine; we create new memory each run)
    # Using a shared instance here is intentional so the agent can hold
    # its reasoning chain within a single invocation.
    memory = ConversationBufferMemory(
        memory_key="chat_history",
        return_messages=True,
        input_key="input",
    )

    tools = [ehr_fetcher, pdf_extractor]

    # Prompt
    prompt = get_eligibility_prompt()

    # Agent
    agent = create_structured_chat_agent(llm=llm, tools=tools, prompt=prompt)

    # Executor
    _eligibility_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        memory=memory,
        max_iterations=8,
        verbose=True,
        handle_parsing_errors=True,
    )
    return _eligibility_executor


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

    executor = get_eligibility_executor()

    # ── 1. PRE-EXTRACT DATA ──────────────────
    policy_text = "ERROR: Failed to extract policy."
    ehr_data = "ERROR: Failed to fetch EHR data."

    try:
        from tools.pdf_extractor import extract_raw_text
        policy_text = extract_raw_text(pdf_path)
    except Exception as e:
        print(f"[eligibility_agent] PDF Extraction failed: {e}")

    try:
        from tools.ehr_fetcher import fetch_extracted_data_by_case
        raw_ehr = fetch_extracted_data_by_case(case_id)
        # Use default=str to handle datetime/date objects
        ehr_data = json.dumps(raw_ehr, indent=2, default=str) if raw_ehr else "No specific patient data found."
    except Exception as e:
        print(f"[eligibility_agent] EHR Fetch failed: {e}")

    result = executor.invoke({
        "case_id":  case_id,
        "pdf_path": pdf_path,
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

    raw_output = result.get("output", "")
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
                db_case.status = "APPROVED" # Or another appropriate terminal state
            else:
                db_case.status = "DENIED"
            
            db.add(db_case)
            db.commit()
            db.refresh(db_case)
            print(f"[eligibility_agent] Persisted results for {case_id}")
    except Exception as e:
        print(f"[eligibility_agent] Persistence failed for {case_id}: {e}")
        db.rollback()
    finally:
        db.close()

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
