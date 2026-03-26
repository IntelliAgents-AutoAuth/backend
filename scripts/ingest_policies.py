import os
import sys

# Ensure backend root is on sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
load_dotenv()

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

def ingest_policies():
    print("Loading test_doc.pdf...")
    pdf_path = os.path.join(backend_dir, "policy-pdfs", "aetna", "test_doc.pdf")
    
    if not os.path.exists(pdf_path):
        print(f"Error: {pdf_path} does not exist.")
        return

    # 1. Load Document
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()
    print(f"Loaded {len(docs)} pages.")

    # 2. Chunk Text
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        separators=["\n\n", "\n", ".", " ", ""],
    )
    splits = text_splitter.split_documents(docs)
    print(f"Split document into {len(splits)} chunks.")

    # 3. Create Vector DB
    persist_dir = os.path.join(backend_dir, ".chroma_db")
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    print(f"Embedding and saving to {persist_dir}...")
    vectorstore = Chroma.from_documents(
        documents=splits,
        embedding=embeddings,
        persist_directory=persist_dir,
        collection_name="policies_collection",
    )
    vectorstore.persist()
    print("Ingestion complete. Chroma DB saved locally.")

if __name__ == "__main__":
    ingest_policies()
