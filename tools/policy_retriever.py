import os
import os
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_vectorstore = None

def get_policy_vectorstore():
    """Lazy load the Chroma vector database."""
    global _vectorstore
    persist_dir = os.path.join(backend_dir, ".chroma_db")
    
    if not os.path.exists(persist_dir):
        return None
        
    if _vectorstore is None:
        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        _vectorstore = Chroma(
            persist_directory=persist_dir,
            embedding_function=embeddings,
            collection_name="policies_collection"
        )
    return _vectorstore

def search_policy_criteria(doc_type: str) -> str:
    """
    Search the structured policy RAG database for a specific doc_type:
    'required_documents', 'eligibility_criteria', or 'pa_document_format'.
    Returns the explicitly extracted chunk.
    """
    db = get_policy_vectorstore()
    if not db:
        return "RAG DATABASE NOT FOUND. Please run scripts/ingest_policies.py first."
        
    results = db.get(where={"doc_type": doc_type})
    if not results or not results.get("documents") or len(results["documents"]) == 0:
        return f"No metadata match for type: {doc_type}"
        
    return results["documents"][0]


