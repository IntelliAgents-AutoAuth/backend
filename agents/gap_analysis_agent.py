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
from langchain_classic.agents import AgentExecutor, create_structured_chat_agent
from langchain_classic.memory import ConversationBufferMemory

from prompts.gap_analysis_prompts import get_gap_analysis_prompt
from tools.ehr_fetcher import ehr_fetcher
from tools.pdf_extractor import pdf_extractor
from tools.gap_validator import gap_validator_tool

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
# LAZY SINGLETON
# ─────────────────────────────────────────
_agent_executor = None


def get_agent_executor():
    """Lazy initialization — agent created once, reused for all calls."""
    global _agent_executor
    if _agent_executor is not None:
        return _agent_executor

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("[gap_analysis_agent] WARNING: GOOGLE_API_KEY is not set.")

    # ── 2. LLM ──────────────────────────────
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-lite",
        temperature=0,
        google_api_key=api_key
    )

    # ── 3. MEMORY ────────────────────────────
    memory = ConversationBufferMemory(
        memory_key="chat_history",
        return_messages=True,
        input_key="input",
         output_key="output"  
    )

    # ── 4. TOOLS ─────────────────────────────
    tools = [
        ehr_fetcher,
        pdf_extractor,
        gap_validator_tool
    ]

    # ── 5. PROMPT ────────────────────────────
    # Instructions are in system prompt — NOT in agent_input
    prompt = get_gap_analysis_prompt()

    # ── 6. AGENT ─────────────────────────────
    agent = create_structured_chat_agent(
        llm=llm,
        tools=tools,
        prompt=prompt
    )

    # ── 7. EXECUTOR ──────────────────────────
    _agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        memory=memory,
        max_iterations=6,
        verbose=False,
        handle_parsing_errors=True,
        return_intermediate_steps=False
    )

    return _agent_executor


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
    patient_name = props.get("patient_name", "Unknown")

    # ── Default PDF for demo/testing ─────────
    if not pdf_path:
        pdf_path = os.path.join(
            backend_dir, "policy-pdfs", "aetna", "test_doc.pdf"
        )

    print(f"\n[gap_analysis_agent] --- Started for {case_id} ---")

    # ── agent_input — data only, NO instructions ──
    # Instructions are in system prompt (gap_analysis_prompts.py)
    # agent_input only passes case specific data
    agent_input = {
        "input": f"""
Please perform a gap analysis for:
- Case ID      : {case_id}
- Patient Name : {patient_name}
- PDF Path     : {pdf_path}

INSTRUCTIONS:
1. CALL `pdf_extractor` to get the policy requirements.
2. CALL `ehr_fetcher` to get the patient record.
3. Compare them and return the Gap Analysis JSON.
"""
    }

    result = await get_agent_executor().ainvoke(agent_input)
    output = result.get("output")

    if isinstance(output, dict):
        output = json.dumps(output, indent=2)

    try:
        parsed = json.loads(output)
    except Exception:
        parsed = {"raw": output}

    # ── PERSISTENCE ──────────────────────────
    # Create a fresh DB session for the background task
    db = SessionLocal()
    try:
        db_case = crud_case.get_case(db, case_id=case_id)
        if db_case:
            summary = parsed.get("summary", {})
            db_case.gap_result = parsed
            db_case.status     = parsed.get("status", db_case.status)
            db_case.total_required = summary.get("total_required")
            db_case.total_matched  = summary.get("total_matched")
            db_case.total_missing  = summary.get("total_missing")
            db_case.gap_percentage = summary.get("gap_percentage")
            
            db.add(db_case)
            db.commit()
            db.refresh(db_case)
            print(f"[gap_analysis_agent] Persisted results for {case_id}")
    except Exception as e:
        print(f"[gap_analysis_agent] Persistence failed for {case_id}: {e}")
        db.rollback()
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