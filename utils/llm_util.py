import os
import time
from typing import List, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from core.model_routing import get_model_order

# Base directory for the backend
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def build_llm(model: str, api_key: str, temperature: float = 0):
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        google_api_key=api_key,
    )

def _get_api_keys() -> List[str]:
    """Load all matching GOOGLE_API_KEY* from environment."""
    load_dotenv(os.path.join(backend_dir, ".env"))
    keys = []
    
    # Check primary key
    primary = os.getenv("GOOGLE_API_KEY")
    if primary:
        keys.append(primary)
    
    # Check for additional keys in sequence (GOOGLE_API_KEY_2, GOOGLE_API_KEY_3, etc.)
    i = 2
    while True:
        key = os.getenv(f"GOOGLE_API_KEY_{i}")
        if not key:
            break
        keys.append(key)
        i += 1
        
    return keys

class RobustLLM:
    """
    A wrapper that provides a pre-configured LangChain ChatGoogleGenerativeAI instance.
    If a quota error occurs during an invoke call, it can be handled by the caller,
    but this utility simplifies fetching the keys.
    """
    
    @staticmethod
    def get_llm(model: str = "gemini-2.5-flash", temperature: float = 0):
        keys = _get_api_keys()
        if not keys:
            print("[llm_util] ERROR: No Google API keys found in .env!")
            return None
            
        # For now, we return the first key. 
        # The agents will be updated to handle rotation if this key fails.
        return build_llm(model=model, api_key=keys[0], temperature=temperature)

    @staticmethod
    def get_llm_for_task(task: str, temperature: float = 0):
        keys = _get_api_keys()
        if not keys:
            print("[llm_util] ERROR: No Google API keys found in .env!")
            return None
        model_order = get_model_order(task)
        if not model_order:
            print(f"[llm_util] ERROR: No model order configured for task '{task}'.")
            return None
        # Returns the primary model for this task. Callers can iterate full order if needed.
        return build_llm(model=model_order[0], api_key=keys[0], temperature=temperature)

def get_keys() -> List[str]:
    return _get_api_keys()
