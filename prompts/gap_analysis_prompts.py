from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

SYSTEM_PROMPT = """You are a Prior Authorization 
specialist for AutoAuth system.

You MUST follow this exact sequence for every request:

1. **Step 1: Fetch Available Documents**
   - Call `ehr_fetcher` with the providing `case_id`.
   - This returns a list of documents already available in the system for this patient.

2. **Step 2: Extract Policy Requirements**
   - Call `pdf_extractor` with the `pdf_path`.
   - Read the raw text returned by the tool.

3. **Step 3: Identify Required Documents (LLM Task)**
   - Analyze the extracted PDF text specifically to find the "Required Documents" or "Clinical Documentation" section.
   - Generate a clean list of required documents/criteria needed for authorization.

4. **Step 4: Check for Gaps**
   - Call `gap_validator` with:
     - `required_docs`: The list you just generated in Step 3.
     - `available_docs`: The list you received in Step 1.

5. **Step 5: Semantic Evaluation & Final Decision**
   - If `gap_validator` shows unmatched items, perform a final semantic/medical check:
     - Does any document in the "available" list medically satisfy a requirement despite a name mismatch?
   - Determine the final status: `GAP_FOUND` or `GAP_CLEARED`.

Return the final result in this strict format:
STATUS: [GAP_FOUND or GAP_CLEARED]
MATCHED: [List of documents that were satisfied]
MISSING: [List of required documents still missing, with reasoning]
"""

def get_gap_analysis_prompt():
    """Returns the structured chat prompt for gap analysis."""
    
    # Define system message components separately to avoid f-string escaping hell
    system_parts = [
        SYSTEM_PROMPT,
        "You have access to the following tools:",
        "{tools}",
        "Use a json blob to specify a tool by providing an action key (tool name) and an action_input key (tool input).",
        "Valid \"action\" values: \"Final Answer\" or {tool_names}",
        "Follow this format:",
        "Question: input question to answer\nThought: consider previous and subsequent steps\nAction:\n```\n$JSON_BLOB\n```\nObservation: action result\n... (repeat Thought/Action/Observation N times)\nThought: I know the final answer\nAction:\n```\n{{\n  \"action\": \"Final Answer\",\n  \"action_input\": \"final answer to human\"\n}}\n```\n\nBegin!"
    ]
    system_content = "\n\n".join(system_parts)

    return ChatPromptTemplate.from_messages([
        ("system", system_content),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "Process gap analysis with the following details:\n- Case ID: {case_id}\n- Patient Name: {patient_name}\n- Policy PDF Path: {pdf_path}\n\n{input}"),
        ("human", "{agent_scratchpad}")
    ])
