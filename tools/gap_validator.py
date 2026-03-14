from langchain_core.tools import tool

def gap_validator(required_docs: list, available_docs: list) -> dict:
    """
    Tool 3 — Compares required docs vs
    available docs. Plain Python first,
    returns unmatched items for LLM
    semantic matching.
    NO LLM here — plain code comparison.
    """
    matched = []
    unmatched = []

    for required in required_docs:
        found = False
        for ehr in available_docs:
            if (required.lower() in ehr["name"].lower() or
                    ehr["name"].lower() in required.lower()):
                matched.append({
                    "required": required,
                    "matched_to": ehr["name"],
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
