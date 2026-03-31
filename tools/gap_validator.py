from langchain_core.tools import tool


def gap_validator(required_docs: list, available_docs: list) -> dict:
    """
    Tool 3 — Compares required docs vs available docs.

    Step 1 → Plain Python exact/partial match (free, instant)
    Step 2 → Returns unmatched items so LLM can do semantic matching

    Input:
      required_docs  → list of strings from PDF extraction
                       e.g. ["echocardiogram report", "lab results"]

      available_docs → list of dicts or strings from EHR
                       e.g. [{"name": "echo_report", "date": "2024-01-15"}]
                       or   ["echo_report", "BNP_lab_test"]

    Output:
      {
        "matched":            [ {required, matched_to, type} ],
        "unmatched_required": [ "doc1", "doc2" ],
        "needs_llm":          true | false
      }
    """
    matched   = []
    unmatched = []

    for required in required_docs:

        # normalise required name
        req_lower = required.lower().strip()
        found = False

        for ehr in available_docs:

            # handle dict or plain string
            if isinstance(ehr, dict):
                ehr_name = ehr.get("name", "") or ehr.get("document_name", "")
            else:
                ehr_name = str(ehr)

            ehr_lower = ehr_name.lower().strip()

            # exact or partial match
            if req_lower in ehr_lower or ehr_lower in req_lower:
                matched.append({
                    "required":   required,
                    "matched_to": ehr_name,
                    "type":       "EXACT"
                })
                found = True
                break

        if not found:
            unmatched.append(required)

    # logging for debug removed (was print statement)

    return {
        "matched":            matched,
        "unmatched_required": unmatched,
        "needs_llm":          len(unmatched) > 0
    }


# Register as LangChain tool
gap_validator_tool = tool(gap_validator)