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
# 1. ENVIRONMENT
# ─────────────────────────────────────────

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# ─────────────────────────────────────────
# 2. LLM
# ─────────────────────────────────────────

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    google_api_key=GOOGLE_API_KEY
)

# ─────────────────────────────────────────
# 3. MEMORY
# ─────────────────────────────────────────

memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True,
    input_key="input"
)

# ─────────────────────────────────────────
# 4. TOOLS (imported)
# ─────────────────────────────────────────

# Tools are imported from external modules in the tools/ directory.


# ─────────────────────────────────────────
# 5. ALL TOOLS LIST
# ─────────────────────────────────────────

tools = [
    ehr_fetcher,
    pdf_extractor,
    gap_validator_tool
]

# ─────────────────────────────────────────
# 6. PROMPT TEMPLATE
# ─────────────────────────────────────────

prompt = get_gap_analysis_prompt()

# ─────────────────────────────────────────
# 7. AGENT
# ─────────────────────────────────────────

agent = create_structured_chat_agent(
    llm=llm,
    tools=tools,
    prompt=prompt
)

# ─────────────────────────────────────────
# 8. AGENT EXECUTOR (orchestrator)
# ─────────────────────────────────────────

agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    memory=memory,
    max_iterations=6,        # max 6 retries
    verbose=True,            # shows every step
    handle_parsing_errors=True
)

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

    # Invoke agent with structured props
    result = agent_executor.invoke({
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