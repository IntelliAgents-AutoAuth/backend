import os
import sys

# Add the backend directory to sys.path to ensure local imports work
# This must happen before any local imports
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

# Use the 'langchain_classic' package for core components in this environment
from langchain_classic.agents import AgentExecutor
from langchain_classic.agents import create_structured_chat_agent
from langchain_classic.memory import ConversationBufferMemory

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from prompts.gap_analysis_prompts import get_gap_analysis_prompt
from tools.ehr_fetcher import ehr_fetcher
from tools.pdf_extractor import pdf_extractor
from tools.gap_validator import gap_validator_tool

# ─────────────────────────────────────────
# 1. ENVIRONMENT & SINGLETONS
# ─────────────────────────────────────────

# Load environment variables from the backend directory
load_dotenv(os.path.join(backend_dir, ".env"))

_agent_executor = None

def get_agent_executor():
    """Lazy initialization of the agent executor to avoid crashes on import."""
    global _agent_executor
    if _agent_executor is not None:
        return _agent_executor

    # Load environment variables here, just before they are needed for the LLM
    # This ensures .env is loaded only when the agent is first accessed.
    load_dotenv(os.path.join(backend_dir, ".env"))

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("[gap_analysis_agent] WARNING: GOOGLE_API_KEY is not set.")

    # 2. LLM
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", 
        temperature=0,
        google_api_key=api_key
    )

    # 3. MEMORY
    memory = ConversationBufferMemory(
        memory_key="chat_history",
        return_messages=True,
        input_key="input"
    )

    # 4. TOOLS
    tools = [
        ehr_fetcher,
        pdf_extractor,
        gap_validator_tool
    ]

    # 5. PROMPT
    prompt = get_gap_analysis_prompt()

    # 6. AGENT
    agent = create_structured_chat_agent(
        llm=llm,
        tools=tools,
        prompt=prompt
    )

    # 7. EXECUTOR
    _agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        memory=memory,
        max_iterations=6,
        verbose=True,
        handle_parsing_errors=True
    )
    return _agent_executor

# ─────────────────────────────────────────
# 9. RUN AGENT — call this from FastAPI
# ─────────────────────────────────────────

def run_gap_analysis(props: dict) -> dict:
    """
    Main function — call this from FastAPI endpoint.
    
    Input:
      props = {
        "case_id": str,
        "patient_name": str,
        "pdf_path": str (optional)
      }
    
    Output:
      {
        "case_id": str,
        "output": str
      }
    """
    case_id = props.get("case_id")
    pdf_path = props.get("pdf_path")
    patient_name = props.get("patient_name", "Unknown")

    # Default PDF path for testing/demo if none provided
    if not pdf_path:
        default_dir = os.path.join("policy-pdfs", "aetna")
        default_filename = "test_doc.pdf"
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pdf_path = os.path.join(backend_dir, default_dir, default_filename)

    # Invoke agent with structured props using lazy initialization
    agent_exec = get_agent_executor()
    result = agent_exec.invoke({
        "case_id": case_id,
        "patient_name": patient_name,
        "pdf_path": pdf_path,
        "input": "Initiate gap analysis based on the provided case details."
    })

    return {
        "case_id": case_id,
        "output": result["output"]
    }


# ─────────────────────────────────────────
# TEST
# ─────────────────────────────────────────

if __name__ == "__main__":
    result = run_gap_analysis(
        case_id="CASE_001",
        pdf_path="policy.pdf"
    )
    print(result)