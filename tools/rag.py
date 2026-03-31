"""
RAG (Retrieval-Augmented Generation) Module
===========================================

This module implements the 'Search' capability of our Platform. It allows 
AI agents to 'Look Up' specific insurance company policies and clinical 
evidence on the fly.

Retriever Paths:
----------------
1. **Policy Retrieval**: Uses a Chroma vector database (or JSON fallback) 
   to find matching eligibility rules, mandated documents, and required 
   formatting based on the Payer Name and CPT code.
2. **Patient Evidence Retrieval**: Uses a dedicated vectorstore 
   ('.chroma_db_patients') to perform semantic search across the 
   patient's medical history for relevant snippets of medical necessity.

Features:
---------
- **Lazy Loading**: Embeddings and Vectorstores are only loaded when 
  first accessed, saving system resources.
- **Persistent Caching**: Search results are cached across process 
  restarts via 'policy_cache' and 'general_cache'.
"""

import os
import json
import time
import logging
from typing import List, Dict, Any, Optional
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from utils.cache_manager import policy_cache, rules_cache, general_cache

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SHARED RESOURCES
# ─────────────────────────────────────────────────────────────────────────────

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_embeddings = None

def get_embeddings():
    """Lazy load the shared embedding model."""
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    return _embeddings

# ─────────────────────────────────────────────────────────────────────────────
# POLICY RETRIEVAL
# ─────────────────────────────────────────────────────────────────────────────

_policy_vectorstore = None

def get_policy_vectorstore():
    """Lazy load the Chroma vector database for policies."""
    global _policy_vectorstore
    persist_dir = os.path.join(backend_dir, ".chroma_db")
    
    if not os.path.exists(persist_dir):
        return None
        
    if _policy_vectorstore is None:
        try:
            _policy_vectorstore = Chroma(
                persist_directory=persist_dir,
                embedding_function=get_embeddings(),
                collection_name="policies_collection"
            )
        except Exception as e:
            logger.warning(f"Failed to initialize Policy ChromaDB: {e}")
            return None
    return _policy_vectorstore

def search_policy_criteria_chromadb(doc_type: str, payer: str | None = None, cpt: str | None = None) -> str | None:
    """Search ChromaDB for policy data."""
    db = get_policy_vectorstore()
    if not db:
        return None
        
    try:
        conditions = [{"doc_type": doc_type}]
        if payer:
            conditions.append({"payer": payer})
        if cpt:
            conditions.append({"cpt": cpt})
        
        where_filter = {"$and": conditions} if len(conditions) > 1 else conditions[0]
            
        results = db.get(where=where_filter)
        if not results or not results.get("documents"):
            return None
        
        all_docs = results["documents"]
        combined_data = "\n\n--- NEXT POLICY FRAGMENT ---\n\n".join(
            [d for d in all_docs if d and isinstance(d, str) and len(d.strip()) >= 10]
        )
        
        return combined_data or None
    except Exception as e:
        logger.warning(f"ChromaDB query failed for {doc_type} (payer={payer}): {e}")
        return None

def search_policy_criteria_json(doc_type: str, payer: str | None = None, cpt: str | None = None) -> str | None:
    """Fallback: search the extracted_policy_rules.json file."""
    try:
        rules_data = rules_cache.load()
        if not rules_data or not isinstance(rules_data, list):
            return None
        
        target_policy = None
        if payer or cpt:
            payer_lower = (payer.lower().replace(" ", "-") if payer else "")
            payer_raw = (payer.lower() if payer else "")
            cpt_str = (str(cpt) if cpt else "")
            
            for policy in rules_data:
                file_name = policy.get("file", "").lower()
                if (payer and (payer_raw in file_name or payer_lower in file_name)) and (cpt_str in file_name):
                    target_policy = policy
                    break
                
                if payer and not target_policy:
                    if payer_lower in file_name or payer_raw in file_name:
                        target_policy = policy
            
            if not target_policy and cpt:
                for policy in rules_data:
                    if cpt_str in policy.get("file", "").lower():
                        target_policy = policy
                        break
            
            if not target_policy and len(rules_data) > 0:
                target_policy = rules_data[0]
        else:
            target_policy = rules_data[0] if rules_data else None

        if not target_policy:
            return None
            
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
        return result if len(result.strip()) >= 10 else None
    except Exception as e:
        logger.warning(f"JSON fallback query failed: {e}")
        return None

def search_policy_criteria(doc_type: str, payer: str | None = None, cpt: str | None = None) -> str:
    """Main entry point for policy retrieval with caching and fallback."""
    cache_key = f"{payer}:{cpt}:{doc_type}"
    cached_data = policy_cache.get(cache_key, ttl=3600)
    if cached_data:
        return cached_data
    
    json_data = search_policy_criteria_json(doc_type, payer, cpt)
    if json_data:
        policy_cache.set(cache_key, json_data)
        return json_data
    
    rag_data = search_policy_criteria_chromadb(doc_type, payer, cpt)
    if rag_data:
        policy_cache.set(cache_key, rag_data)
        return rag_data
    
    raise ValueError(f"Policy data '{doc_type}' for payer '{payer}'/CPT '{cpt}' not found.")

# ─────────────────────────────────────────────────────────────────────────────
# PATIENT RETRIEVAL
# ─────────────────────────────────────────────────────────────────────────────

class PatientRetriever:
    """RAG service for patient documents."""
    
    def __init__(self):
        self.persist_dir = os.path.join(backend_dir, ".chroma_db_patients")
        self.collection_name = "patient_evidence"
        self._vectorstore = None

    def get_vectorstore(self):
        """Lazy load the patient vector database."""
        if self._vectorstore is None:
            try:
                self._vectorstore = Chroma(
                    persist_directory=self.persist_dir,
                    embedding_function=get_embeddings(),
                    collection_name=self.collection_name
                )
            except Exception as e:
                logger.error(f"Failed to initialize Patient ChromaDB: {e}")
                return None
        return self._vectorstore

    def search_evidence(self, case_id: str, query: str, k: int = 5) -> str:
        """Search for relevant evidence in patient documents."""
        db = self.get_vectorstore()
        if not db:
            return ""

        cache_key = f"patient_rag:{case_id}:{query}"
        cached = general_cache.get(cache_key, ttl=3600)
        if cached:
            return cached

        try:
            results = db.similarity_search(query, k=k, filter={"case_id": case_id})
            if not results:
                return ""
            
            evidence_chunks = [f"--- FROM {doc.metadata.get('source_file', 'Unknown')} ---\n{doc.page_content}" for doc in results]
            evidence_text = "\n\n".join(evidence_chunks)
            general_cache.set(cache_key, evidence_text)
            return evidence_text
        except Exception as e:
            logger.error(f"Patient RAG search failed for {case_id}: {e}")
            return ""

# Singleton instance
patient_retriever = PatientRetriever()
