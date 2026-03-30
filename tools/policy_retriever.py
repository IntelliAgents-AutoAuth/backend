import os
import json
import time
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_vectorstore = None


# ─────────────────────────────────────────────────────────────
# OPTIMIZATION: Policy Cache (1-hour TTL)
# ─────────────────────────────────────────────────────────────
class PolicyCache:
    """In-memory cache for policy queries with time-based expiration."""
    
    def __init__(self, ttl_seconds=3600):
        """
        Initialize cache with optional TTL.
        
        Args:
            ttl_seconds: Time-to-live for cached entries (default: 1 hour)
        """
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get(self, key: str) -> str | None:
        """
        Retrieve value from cache if it exists and hasn't expired.
        
        Args:
            key: Cache key (format: "{payer}:{doc_type}")
        
        Returns:
            Cached value or None if not found/expired
        """
        if key not in self.cache:
            return None
        
        data, timestamp = self.cache[key]
        age_seconds = time.time() - timestamp
        
        if age_seconds < self.ttl:
            return data  # Still valid
        
        # Expired, remove and return None
        del self.cache[key]
        return None
    
    def set(self, key: str, value: str):
        """
        Store value in cache with current timestamp.
        
        Args:
            key: Cache key (format: "{payer}:{doc_type}")
            value: Policy data to cache
        """
        self.cache[key] = (value, time.time())
    
    def clear(self):
        """Clear all cached entries."""
        self.cache.clear()
    
    def stats(self) -> dict:
        """Return cache statistics."""
        return {
            "total_entries": len(self.cache),
            "ttl_seconds": self.ttl
        }


# Global cache instance
_policy_cache = PolicyCache(ttl_seconds=3600)  # 1 hour TTL


def get_policy_vectorstore():
    """Lazy load the Chroma vector database. Returns None if unavailable."""
    global _vectorstore
    persist_dir = os.path.join(backend_dir, ".chroma_db")
    
    if not os.path.exists(persist_dir):
        return None
        
    if _vectorstore is None:
        try:
            embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
            _vectorstore = Chroma(
                persist_directory=persist_dir,
                embedding_function=embeddings,
                collection_name="policies_collection"
            )
        except Exception as e:
            import logging
            logging.warning(f"Failed to initialize ChromaDB: {e}")
            return None
    return _vectorstore


def search_policy_criteria_chromadb(doc_type: str, payer: str | None = None) -> str | None:
    """
    Search the ChromaDB vector database for policy data with optional payer filtering.
    Returns policy data string or None if not found/unavailable.
    
    Args:
        doc_type: One of 'required_documents', 'eligibility_criteria', 'pa_document_format'
        payer: Optional payer name (e.g., 'Aetna', 'Cigna', 'United Healthcare')
               If None, returns first match
    
    Returns:
        Policy data string, or None if not available
    """
    db = get_policy_vectorstore()
    if not db:
        return None
        
    try:
        # Build filter with optional payer
        where_filter = {"doc_type": doc_type}
        if payer:
            where_filter["payer"] = payer
        
        results = db.get(where=where_filter)
        if not results or not results.get("documents") or len(results["documents"]) == 0:
            return None
        
        data = results["documents"][0]
        # Validate data is meaningful (not too short or obviously empty)
        if not data or (isinstance(data, str) and len(data.strip()) < 10):
            return None
        
        return data
    except Exception as e:
        import logging
        logging.warning(f"ChromaDB query failed for {doc_type} (payer={payer}): {e}")
        return None


def search_policy_criteria_json(doc_type: str, payer: str | None = None) -> str | None:
    """
    Fallback: search the extracted_policy_rules.json file for policy data with optional payer filtering.
    
    Args:
        doc_type: One of 'required_documents', 'eligibility_criteria', 'pa_document_format'
        payer: Optional payer name (e.g., 'Aetna', 'Cigna', 'United Healthcare')
               If None, returns first match
    
    Returns:
        Policy data string, or None if not available
    """
    try:
        rules_path = os.path.join(backend_dir, "policy-pdfs", "extracted_policy_rules.json")
        if not os.path.exists(rules_path):
            return None
        
        with open(rules_path, 'r', encoding='utf-8') as f:
            rules_data = json.load(f)
        
        if not rules_data or not isinstance(rules_data, list) or len(rules_data) == 0:
            return None
        
        # Find policy by payer or use first
        target_policy = None
        if payer:
            # Try to match policy by payer name in filename
            payer_lower = payer.lower().replace(" ", "-")
            for policy in rules_data:
                file_name = policy.get("file", "").lower()
                # Match if payer name appears in the file path
                if payer_lower in file_name or payer.lower() in file_name:
                    target_policy = policy
                    break
            
            # If not found by filename, no match for this payer
            if not target_policy:
                return None
        else:
            # Use first policy when no payer specified
            target_policy = rules_data[0]
        
        target = target_policy.get("extracted_data", {})
        
        if doc_type == "eligibility_criteria":
            data = target.get("eligibility_criteria", [])
        elif doc_type == "required_documents":
            data = target.get("required_documents", [])
        elif doc_type == "pa_document_format":
            data = target.get("format", {})
        else:
            return None
        
        result = json.dumps(data, indent=2)
        # Validate it's not empty
        if len(result.strip()) < 10:
            return None
        
        return result
    except Exception as e:
        import logging
        logging.warning(f"JSON fallback query failed for {doc_type} (payer={payer}): {e}")
        return None


def search_policy_criteria(doc_type: str, payer: str | None = None) -> str:
    """
    Search for policy criteria with automatic fallback and optional payer filtering.
    
    Try ChromaDB first, then extracted_policy_rules.json.
    **OPTIMIZED**: Checks in-memory cache first (1-hour TTL).
    Raises ValueError if no policy data available from any source.
    
    Args:
        doc_type: One of 'required_documents', 'eligibility_criteria', 'pa_document_format'
        payer: Optional payer name (e.g., 'Aetna', 'Cigna', 'United Healthcare')
               If None, returns first match from any payer
    
    Returns:
        Policy data as string
    
    Raises:
        ValueError: If policy data not available from any source
    """
    import logging
    
    # ──── CACHE CHECK (NEW - Optimization 2) ────
    cache_key = f"{payer}:{doc_type}"
    cached_data = _policy_cache.get(cache_key)
    if cached_data:
        logging.info(f"[CACHE HIT] Policy '{doc_type}' (payer={payer}) from in-memory cache")
        return cached_data
    
    # ──── CHROMADB QUERY ────
    rag_data = search_policy_criteria_chromadb(doc_type, payer)
    if rag_data:
        logging.info(f"Loaded policy data '{doc_type}' from ChromaDB (payer={payer})")
        # Store in cache for future queries
        _policy_cache.set(cache_key, rag_data)
        return rag_data
    
    # ──── JSON FALLBACK ────
    json_data = search_policy_criteria_json(doc_type, payer)
    if json_data:
        logging.info(f"Loaded policy data '{doc_type}' from extracted_policy_rules.json (payer={payer}, ChromaDB unavailable)")
        # Store in cache for future queries
        _policy_cache.set(cache_key, json_data)
        return json_data
    
    # ──── NO DATA AVAILABLE ────
    payer_str = f" for payer '{payer}'" if payer else ""
    raise ValueError(
        f"Policy data '{doc_type}'{payer_str} not available. "
        f"ChromaDB not initialized (run scripts/ingest_policies.py) "
        f"and extracted_policy_rules.json not found or empty."
    )


