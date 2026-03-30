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

# Map directory names to standard payer names
PAYER_DIRECTORY_MAP = {
    "aetna": "Aetna",
    "bcbs": "BCBS",
    "cigna": "Cigna",
    "cms": "CMS",
    "humana": "Humana",
    "united-healthcare": "United Healthcare",
}


def extract_payer_from_path(pdf_path: str) -> str | None:
    """
    Extract payer name from the PDF file path.
    
    Example: /backend/policy-pdfs/aetna/test_doc.pdf → "Aetna"
    """
    path_parts = pdf_path.lower().split(os.sep)
    for i, part in enumerate(path_parts):
        if part == "policy-pdfs" and i + 1 < len(path_parts):
            dir_name = path_parts[i + 1]
            return PAYER_DIRECTORY_MAP.get(dir_name)
    return None


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


def ingest_policies_for_payer(payer_dir: str, payer_name: str, vectorstore, llm, prompt_template):
    """
    Ingest all policies from a specific payer directory.
    
    Args:
        payer_dir: Full path to the payer directory (e.g., /backend/policy-pdfs/aetna)
        payer_name: Standardized payer name (e.g., "Aetna")
        vectorstore: ChromaDB vectorstore instance
        llm: LLM instance for extraction
        prompt_template: Prompt template for policy extraction
    """
    if not os.path.exists(payer_dir):
        print(f"Payer directory not found: {payer_dir}")
        return
    
    # Find all PDF files in this payer's directory
    pdf_files = [f for f in os.listdir(payer_dir) if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        print(f"No PDF files found in {payer_dir}")
        return
    
    print(f"\n{'='*60}")
    print(f"Processing policies for {payer_name} ({len(pdf_files)} files)")
    print(f"{'='*60}")
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(payer_dir, pdf_file)
        
        # Check if this policy is already ingested
        existing = vectorstore.get(where={
            "payer": payer_name,
            "source_file": pdf_file
        })
        
        if existing and existing.get("ids") and len(existing["ids"]) > 0:
            print(f"✓ Policy '{pdf_file}' for {payer_name} already exists. Skipping...")
            continue
        
        print(f"\n→ Processing {pdf_file} for {payer_name}...")
        result = extract_policy_details_sync(pdf_path, llm, prompt_template)
        
        if "error" in result:
            print(f"✗ Extraction failed: {result['error']}")
            continue
        
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
        
        # Generate unique IDs incorporating payer
        doc_id_base = f"{payer_name.lower().replace(' ', '_')}_{pdf_file.replace('.', '_')}"
        
        # Save to ChromaDB with payer metadata
        print(f"  → Saving structured data to ChromaDB with payer metadata...")
        try:
            vectorstore.add_texts(
                texts=[str_req_docs, str_elig_rules, str_pa_format],
                metadatas=[
                    {
                        "doc_type": "required_documents",
                        "payer": payer_name,
                        "source_file": pdf_file,
                        "source_path": pdf_path
                    },
                    {
                        "doc_type": "eligibility_criteria",
                        "payer": payer_name,
                        "source_file": pdf_file,
                        "source_path": pdf_path
                    },
                    {
                        "doc_type": "pa_document_format",
                        "payer": payer_name,
                        "source_file": pdf_file,
                        "source_path": pdf_path
                    }
                ],
                ids=[
                    f"{doc_id_base}_req",
                    f"{doc_id_base}_elig",
                    f"{doc_id_base}_format"
                ]
            )
            print(f"  ✓ Successfully stored policy for {payer_name}")
        except Exception as e:
            print(f"  ✗ Error during add_texts: {e}")


def ingest_structured_policy_sync():
    """
    Ingest policies from all payers, discovering them from directory structure.
    Stores payer metadata in ChromaDB.
    """
    persist_dir = os.path.join(backend_dir, ".chroma_db")
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    # Initialize or connect to Chroma
    vectorstore = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
        collection_name="policies_collection"
    )
    
    print("ChromaDB initialized")
    print(f"Persist directory: {persist_dir}")
    
    # Initialize LLM and prompt template once
    llm = RobustLLM.get_llm_for_task(task="policy_extraction")
    prompt_template = get_policy_extraction_prompt()
    
    # Process each payer
    policy_base_dir = os.path.join(backend_dir, "policy-pdfs")
    
    if not os.path.exists(policy_base_dir):
        print(f"Error: Policy directory not found: {policy_base_dir}")
        return
    
    for dir_name, payer_name in PAYER_DIRECTORY_MAP.items():
        payer_dir = os.path.join(policy_base_dir, dir_name)
        ingest_policies_for_payer(payer_dir, payer_name, vectorstore, llm, prompt_template)
    
    print(f"\n{'='*60}")
    print("✓ Policy ingestion completed!")
    print(f"{'='*60}")
    str_elig_rules_lines = ["=== ELIGIBILITY RULES & CRITERIA ==="]
    if isinstance(elig_rules, list):
        for rule in elig_rules:
            if isinstance(rule, dict):
                crit = rule.get("criterion") or rule.get("rule", "Requirement")
                details = rule.get("details", "")
                str_elig_rules_lines.append(f"- {crit}: {details}")
            else:
                str_elig_rules_lines.append(f"- {rule}")

if __name__ == "__main__":
    ingest_structured_policy_sync()
