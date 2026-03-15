from langchain_core.tools import tool

def gap_validator(required_docs: list, available_docs: list) -> dict:
    """
    Tool 3 — Compares required docs vs available docs. 
    Plain Python first, returns unmatched items for LLM semantic matching.
    """
    matched = []
    unmatched = []

    for required in required_docs:
        found = False
        for ehr in available_docs:
            # Handle both dicts with "name" and simple strings
            if isinstance(ehr, dict) and "name" in ehr:
                ehr_name = ehr["name"]
            else:
                ehr_name = str(ehr)

            if (required.lower() in ehr_name.lower() or
                    ehr_name.lower() in required.lower()):
                matched.append({
                    "required": required,
                    "matched_to": ehr_name,
                    "type": "EXACT"
                })
                found = True
                break
        if not found:
            unmatched.append(required)

    return {
        "matched": matched,
        "unmatched_required": unmatched,
        "needs_llm": len(unmatched) > 0
    }

# Tool for use in LangChain agents
gap_validator_tool = tool(gap_validator)
