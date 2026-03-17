import os
import time
from typing import List, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

# Base directory for the backend
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
    def get_llm(model: str = "gemini-2.5-flash-lite", temperature: float = 0):
        keys = _get_api_keys()
        if not keys:
            print("[llm_util] ERROR: No Google API keys found in .env!")
            return None
            
        # For now, we return the first key. 
        # The agents will be updated to handle rotation if this key fails.
        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            google_api_key=keys[0],
        )

def get_keys() -> List[str]:
    return _get_api_keys()
