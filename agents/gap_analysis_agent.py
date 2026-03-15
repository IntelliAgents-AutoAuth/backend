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

from prompts.gap_analysis_prompts import SYSTEM_PROMPT
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
    model="gemini-2.0-flash",
    temperature=0,
    google_api_key=GOOGLE_API_KEY
)

# ─────────────────────────────────────────
# 3. MEMORY
# ─────────────────────────────────────────

memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
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

prompt = ChatPromptTemplate.from_messages([
    ("system", f"{SYSTEM_PROMPT}\n\nYou have access to the following tools:\n{{tools}}\n\nUse a json blob to specify a tool by providing an action key (tool name) and an action_input key (tool input).\n\nValid \"action\" values: \"Final Answer\" or {{tool_names}}\n\nFollow this format:\n\nQuestion: input question to answer\nThought: consider previous and subsequent steps\nAction:\n```\n$JSON_BLOB\n```\nObservation: action result\n... (repeat Thought/Action/Observation N times)\nThought: I know the final answer\nAction:\n```\n{{\n  \"action\": \"Final Answer\",\n  \"action_input\": \"final answer to human\"\n}}\n```\n\nBegin!"),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad")
])

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
    max_iterations=3,        # max 3 retries
    verbose=True,            # shows every step
    handle_parsing_errors=True
)

# ─────────────────────────────────────────
# 9. RUN AGENT — call this from FastAPI
# ─────────────────────────────────────────

def run_gap_analysis(case_id: str, pdf_path: str | None = None) -> dict:
    """
    Main function — call this from FastAPI endpoint.
    
    Input:
      case_id  → from cases table
      pdf_path → uploaded PDF path (optional)
    
    Output:
      {
        status: GAP_FOUND / GAP_CLEARED,
        missing_docs: [...],
        matched_docs: [...]
      }
    """
    # Default PDF path for testing/demo if none provided
    if not pdf_path:
        default_dir = os.path.join("policy-pdfs", "aetna")
        default_filename = "test_doc.pdf"
        # Search for the full path
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pdf_path = os.path.join(backend_dir, default_dir, default_filename)

    result = agent_executor.invoke({
        "input": f"""
        Process gap analysis for:
        Case ID: {case_id}
        PDF Path: {pdf_path or 'None'}
        
        Find all missing documents.
        """
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