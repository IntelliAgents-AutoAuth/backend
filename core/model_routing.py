import os
from typing import List

# Central model routing policy (task -> model order)
# First entry is primary model, later entries are fallbacks.
TASK_MODEL_FALLBACKS: dict[str, list[str]] = {
    "orchestrator_supervisor": ["gemini-2.5-flash-lite", "gemini-2.5-flash"],
    "eligibility": ["gemini-2.5-flash"],
    "gap_analysis": ["gemini-2.5-flash-lite", "gemini-2.5-flash"],
    "summarization": ["gemini-2.5-flash-lite", "gemini-2.5-flash"],
    "pa_document": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
    "policy_extraction": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
    "default": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
}


def get_model_order(task: str) -> List[str]:
    """
    Returns model order for a task from central policy.

    Optional env override:
      MODEL_ORDER_<TASK_UPPER>=model1,model2,model3
    Example:
      MODEL_ORDER_ELIGIBILITY=gemini-2.5-pro,gemini-2.5-flash
    """
    task_key = (task or "default").strip().lower()
    env_key = f"MODEL_ORDER_{task_key.upper()}"
    env_value = os.getenv(env_key)
    if env_value:
        models = [m.strip() for m in env_value.split(",") if m.strip()]
        if models:
            return models

    models = TASK_MODEL_FALLBACKS.get(task_key) or TASK_MODEL_FALLBACKS["default"]
    return list(models)
