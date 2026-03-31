import os
import logging
from typing import List, Dict, Any, Optional
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from utils.cache_manager import general_cache

logger = logging.getLogger(__name__)

class PatientRetriever:
    """
    RAG service for patient documents.
    Handles indexing and retrieval of patient-specific evidence.
    Ensures data isolation using case_id metadata filtering.
    """
    
    def __init__(self):
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.persist_dir = os.path.join(backend_dir, ".chroma_db_patients")
        self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        self.collection_name = "patient_evidence"
        self._vectorstore = None

    def get_vectorstore(self):
        """Lazy load the patient vector database."""
        if self._vectorstore is None:
            try:
                self._vectorstore = Chroma(
                    persist_directory=self.persist_dir,
                    embedding_function=self.embeddings,
                    collection_name=self.collection_name
                )
            except Exception as e:
                logger.error(f"Failed to initialize Patient ChromaDB: {e}")
                return None
        return self._vectorstore

    def search_evidence(self, case_id: str, query: str, k: int = 5) -> str:
        """
        Search for relevant evidence in patient documents for a specific case.
        
        Args:
            case_id: The case identifier for isolation
            query: The clinical question or criteria to match
            k: Number of snippets to return
            
        Returns:
            Concatenated string of relevant evidence
        """
        db = self.get_vectorstore()
        if not db:
            return ""

        # CACHE CHECK: Query-based cache for performance
        cache_key = f"patient_rag:{case_id}:{query}"
        cached = general_cache.get(cache_key, ttl=3600)  # 1 hour TTL
        if cached:
            return cached

        try:
            # IMPORTANT: metadata filter ensures isolation between patients
            results = db.similarity_search(
                query, 
                k=k, 
                filter={"case_id": case_id}
            )
            
            if not results:
                return ""
            
            evidence_chunks = []
            for doc in results:
                source = doc.metadata.get("source_file", "Unknown")
                content = doc.page_content
                evidence_chunks.append(f"--- FROM {source} ---\n{content}")
            
            evidence_text = "\n\n".join(evidence_chunks)
            
            # Store in cache
            general_cache.set(cache_key, evidence_text)
            
            return evidence_text
        except Exception as e:
            logger.error(f"Patient RAG search failed for {case_id}: {e}")
            return ""

# Singleton instance
patient_retriever = PatientRetriever()
