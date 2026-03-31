import os
import json
import time
import logging
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_vectorstore = None
logger = logging.getLogger(__name__)


from utils.cache_manager import policy_cache


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


def search_policy_criteria_chromadb(doc_type: str, payer: str | None = None, cpt: str | None = None) -> str | None:
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
        # Build filter with optional payer — Chroma requires $and for multiple conditions
        conditions = [{"doc_type": doc_type}]
        if payer:
            conditions.append({"payer": payer})
        if cpt:
            conditions.append({"cpt": cpt})
        
        if len(conditions) > 1:
            where_filter = {"$and": conditions}
        else:
            where_filter = conditions[0]
            
        results = db.get(where=where_filter)
        if not results or not results.get("documents") or len(results["documents"]) == 0:
            return None
        
        # OPTIMIZATION: Concatenate ALL matching policy docs instead of just taking the first one
        # This ensures we handle multiple policy PDFs for the same payer (e.g. general + specific)
        all_docs = results["documents"]
        combined_data = "\n\n--- NEXT POLICY FRAGMENT ---\n\n".join(
            [d for d in all_docs if d and isinstance(d, str) and len(d.strip()) >= 10]
        )
        
        if not combined_data:
            return None
            
        logger.info(f"Retrieved {len(all_docs)} matching policy fragments for {doc_type} (payer={payer})")
        return combined_data
    except Exception as e:
        import logging
        logging.warning(f"ChromaDB query failed for {doc_type} (payer={payer}): {e}")
        return None


def search_policy_criteria_json(doc_type: str, payer: str | None = None, cpt: str | None = None) -> str | None:
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
        if payer or cpt:
            # Try to match policy by payer name and cpt in filename (e.g., "United Healthcare_75563.pdf")
            payer_lower = (payer.lower().replace(" ", "-") if payer else "")
            payer_raw = (payer.lower() if payer else "")
            cpt_str = (str(cpt) if cpt else "")
            
            logger.info(f"[search_policy_json] Searching for Payer='{payer}' CPT='{cpt}' in {len(rules_data)} policies")
            
            for policy in rules_data:
                file_name = policy.get("file", "").lower()
                
                # OPTIMIZATION: Prioritize exact matches for both payer AND cpt in filename
                if payer and cpt:
                    if (payer_raw in file_name or payer_lower in file_name) and cpt_str in file_name:
                        target_policy = policy
                        logger.info(f"[search_policy_json] Exact match found (Payer+CPT): {file_name}")
                        break
                
                # Fallback to payer only
                if payer and not target_policy:
                    if payer_lower in file_name or payer_raw in file_name:
                        target_policy = policy
                        logger.info(f"[search_policy_json] Payer-only match found: {file_name}")
            
            # Final fallback: Look for "General" policy if nothing found for insurance but CPT exists
            if not target_policy and cpt:
                for policy in rules_data:
                    file_name = policy.get("file", "").lower()
                    if cpt_str in file_name:
                        target_policy = policy
                        logger.info(f"[search_policy_json] CPT-only match found (General): {file_name}")
                        break
            
            # If still not found by filename, check if there's any policy at all
            if not target_policy and len(rules_data) > 0:
                target_policy = rules_data[0]
                logger.info(f"[search_policy_json] Using first available policy as absolute fallback: {target_policy.get('file')}")
        else:
            # Use first policy when no payer specified
            target_policy = rules_data[0]
            logger.info(f"[search_policy_json] Using first available policy (no filter): {target_policy.get('file')}")
        
        target = target_policy.get("extracted_data", {})
        
        if doc_type == "eligibility_criteria":
            data = target.get("eligibility_criteria", [])
        elif doc_type == "required_documents":
            data = target.get("required_documents", [])
        elif doc_type == "pa_document_format":
            data = target.get("pa_document_format") or target.get("format", {})
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


def search_policy_criteria(doc_type: str, payer: str | None = None, cpt: str | None = None) -> str:
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
    cache_key = f"{payer}:{cpt}:{doc_type}"
    cached_data = policy_cache.get(cache_key, ttl=3600)
    if cached_data:
        logging.info(f"[CACHE HIT] Policy '{doc_type}' (payer={payer}) from in-memory cache")
        return cached_data
    
    # ──── JSON CACHE ("READ THE CODE") ────
    json_data = search_policy_criteria_json(doc_type, payer, cpt)
    if json_data:
        logging.info(f"Loaded policy data '{doc_type}' from extracted_policy_rules.json (payer={payer}, cpt={cpt})")
        # Store in in-memory cache for fast subsequent access
        policy_cache.set(cache_key, json_data)
        return json_data
    
    # ──── CHROMADB FALLBACK ────
    rag_data = search_policy_criteria_chromadb(doc_type, payer, cpt)
    if rag_data:
        logging.info(f"Loaded policy data '{doc_type}' from ChromaDB (payer={payer}, cpt={cpt})")
        # Store in in-memory cache for fast subsequent access
        policy_cache.set(cache_key, rag_data)
        return rag_data
    
    # ──── NO DATA AVAILABLE ────
    payer_str = f" for payer '{payer}'" if payer else ""
    cpt_str = f" with CPT '{cpt}'" if cpt else ""
    raise ValueError(
        f"Policy data '{doc_type}'{payer_str}{cpt_str} not available. "
        f"ChromaDB not initialized (run scripts/ingest_policies.py) "
        f"and extracted_policy_rules.json not found or empty."
    )


