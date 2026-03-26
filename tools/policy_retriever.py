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

def search_policy_criteria(query: str, k: int = 4) -> str:
    """
    Search the policy RAG database for specific criteria based on the patient's condition.
    Returns the concatenated chunks of relevant policy rules.
    """
    db = get_policy_vectorstore()
    if not db:
        return "RAG DATABASE NOT FOUND. Please run scripts/ingest_policies.py first."
        
    results = db.similarity_search(query, k=k)
    if not results:
        return "No relevant policy rules found."
        
    formatted_docs = []
    for i, doc in enumerate(results, 1):
        formatted_docs.append(f"--- Policy Rule Extract {i} ---\n{doc.page_content}")
        
    return "\n\n".join(formatted_docs)
