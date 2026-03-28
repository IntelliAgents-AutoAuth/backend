import os
import sys
import json

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
load_dotenv()

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from utils.llm_util import RobustLLM
from prompts.policy_extraction_prompts import get_policy_extraction_prompt
from pypdf import PdfReader

def extract_policy_details_sync(pdf_path: str, llm, prompt_template) -> dict:
    print(f"Reading {pdf_path}...")
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        
        if not text.strip():
            return {"file": os.path.basename(pdf_path), "error": "No extractable text found."}

        prompt = prompt_template.invoke({"input": text})
        
        print(f"Sent {os.path.basename(pdf_path)} to Gemini for policy extraction (sync)...")
        response = llm.invoke(prompt)
        
        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
            
        print(f"Extracted content: {content[:200]}...")
        return {
            "file": os.path.basename(pdf_path),
            "extracted_data": json.loads(content)
        }
    except Exception as e:
        print(f"Error processing {pdf_path}: {e}")
        return {"file": os.path.basename(pdf_path), "error": str(e)}

def ingest_structured_policy_sync():
    pdf_path = os.path.join(backend_dir, "policy-pdfs", "aetna", "test_doc.pdf")
    if not os.path.exists(pdf_path):
        print(f"Error: {pdf_path} not found.")
        return

    persist_dir = os.path.join(backend_dir, ".chroma_db")
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    # 1. Initialize or connect to Chroma
    vectorstore = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
        collection_name="policies_collection"
    )

    # 2. Check if this PDF is already ingested
    existing = vectorstore.get(where={"source": "test_doc.pdf"})
    if existing and existing.get("ids") and len(existing["ids"]) > 0:
        print("Policy 'test_doc.pdf' already exists in ChromaDB. Skipping LLM extraction.")
        return

    print("Policy NOT in ChromaDB. Running LLM structured extraction (sync)...")

    # 3. Use LLM to extract structured responses
    llm = RobustLLM.get_llm_for_task(task="policy_extraction")
    prompt_template = get_policy_extraction_prompt()
    result = extract_policy_details_sync(pdf_path, llm, prompt_template)

    if "error" in result:
        print(f"Extraction failed: {result['error']}")
        return

    data = result.get("extracted_data", {})
    
    # --- Format Required Documents ---
    req_docs = data.get("required_documents", [])
    str_req_docs_lines = ["=== REQUIRED DOCUMENTS ==="]
    if isinstance(req_docs, list):
        for rd in req_docs:
            if isinstance(rd, dict):
                name = rd.get("document_name") or rd.get("name", "Document")
                reason = rd.get("reason", "No reason provided")
                str_req_docs_lines.append(f"- {name}: {reason}")
            else:
                str_req_docs_lines.append(f"- {rd}")
    str_req_docs = "\n".join(str_req_docs_lines)

    # --- Format Eligibility Criteria ---
    elig_rules = data.get("eligibility_criteria", [])
    str_elig_rules_lines = ["=== ELIGIBILITY RULES & CRITERIA ==="]
    if isinstance(elig_rules, list):
        for rule in elig_rules:
            if isinstance(rule, dict):
                crit = rule.get("criterion") or rule.get("rule", "Requirement")
                details = rule.get("details", "")
                str_elig_rules_lines.append(f"- {crit}: {details}")
            else:
                str_elig_rules_lines.append(f"- {rule}")
    str_elig_rules = "\n".join(str_elig_rules_lines)

    # --- Format PA Document Format ---
    pa_format_data = data.get("pa_document_format", {})
    str_pa_format_lines = ["=== PA DOCUMENT FORMAT ==="]
    if isinstance(pa_format_data, dict):
        instr = pa_format_data.get("instructions", "No specific formatting instructions.")
        forms = pa_format_data.get("required_forms_mentioned", [])
        str_pa_format_lines.append(f"Instructions: {instr}")
        if forms:
            str_pa_format_lines.append(f"Required Forms: {', '.join(forms)}")
    else:
        str_pa_format_lines.append(str(pa_format_data))
    str_pa_format = "\n".join(str_pa_format_lines)

    # 4. Save to Chroma DB with specific metadata tags
    print("Saving structured data to ChromaDB...")
    try:
        vectorstore.add_texts(
            texts=[str_req_docs, str_elig_rules, str_pa_format],
            metadatas=[
                {"doc_type": "required_documents", "source": "test_doc.pdf"},
                {"doc_type": "eligibility_criteria", "source": "test_doc.pdf"},
                {"doc_type": "pa_document_format", "source": "test_doc.pdf"}
            ],
            ids=["test_doc_req", "test_doc_elig", "test_doc_format"]
        )
        print("Successfully populated structured responses in ChromaDB.")
    except Exception as e:
        print(f"Error during add_texts: {e}")

if __name__ == "__main__":
    ingest_structured_policy_sync()
