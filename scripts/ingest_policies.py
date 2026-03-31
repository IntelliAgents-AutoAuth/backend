import os
import sys
import json

# Correctly set backend_dir to the actual 'backend' directory
current_file_path = os.path.abspath(__file__)
scripts_dir = os.path.dirname(current_file_path)
backend_dir = os.path.dirname(scripts_dir)

# Add backend_dir to sys.path so we can import internal modules (utils, prompts, agents, etc.)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Ensure the working directory is the backend root for consistent relative paths
os.chdir(backend_dir)

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from utils.llm_util import RobustLLM
from prompts.policy_extraction_prompts import get_policy_extraction_prompt
from pypdf import PdfReader

# --- Phoenix Instrumentation ---
try:
    from phoenix.otel import register
    from openinference.instrumentation.langchain import LangChainInstrumentor

    # Send traces directly to the Phoenix instance running in main.py
    tracer_provider = register(endpoint="http://127.0.0.1:6006/v1/traces")
    LangChainInstrumentor().instrument(tracer_provider=tracer_provider, skip_dep_check=True)
    print("[observability] LangChain instrumentation connected to existing Phoenix dashboard at :6006.")
except Exception as e:
    print(f"[observability] Skipping Phoenix configuration: {e}")
# -------------------------------

# Map directory names to standard payer names
PAYER_DIRECTORY_MAP = {
    "aetna": "Aetna",
    "bcbs": "BCBS",
    "cigna": "Cigna",
    "cms": "CMS",
    "humana": "Humana",
    "united-healthcare": "United Healthcare",
}

RULES_JSON_PATH = os.path.join(backend_dir, "policy-pdfs", "extracted_policy_rules.json")


def extract_payer_from_path(pdf_path: str) -> str | None:
    """
    Extract payer name from the PDF file path.
    
    Example: /backend/policy-pdfs/aetna/test_doc.pdf >> "Aetna"
    """
    path_parts = pdf_path.lower().split(os.sep)
    for i, part in enumerate(path_parts):
        if part == "policy-pdfs" and i + 1 < len(path_parts):
            dir_name = path_parts[i + 1]
            return PAYER_DIRECTORY_MAP.get(dir_name)
    
    # Fallback: check filename for Payer_CPT.pdf pattern
    filename = os.path.basename(pdf_path).replace("_", " ").lower()
    for dir_name, payer_name in PAYER_DIRECTORY_MAP.items():
        if payer_name.lower() in filename:
            return payer_name
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
        
        # Check if already in ChromaDB
        existing_chroma = vectorstore.get(where={
            "$and": [
                {"payer": payer_name},
                {"source_file": pdf_file}
            ]
        })
        
        is_in_chroma = False
        if existing_chroma and existing_chroma.get("ids") and len(existing_chroma["ids"]) > 0:
            print(f"Policy '{pdf_file}' for {payer_name} already exists in Chroma. Checking JSON...")
            is_in_chroma = True
            
        # Check if already in JSON cache
        is_in_json = False
        if os.path.exists(RULES_JSON_PATH):
            with open(RULES_JSON_PATH, "r", encoding="utf-8") as f:
                try:
                    rules_data = json.load(f)
                    is_in_json = any(r.get("file") == pdf_file for r in rules_data)
                except:
                    pass
        
        if is_in_chroma and is_in_json:
            print(f"Skipping: Policy '{pdf_file}' already in ChromaDB and JSON.")
            continue
        
        print(f"Processing: {pdf_file} for {payer_name}... (InChroma={is_in_chroma}, InJSON={is_in_json})")
        
        # If not in JSON, we need to extract it anyway (which will also update Chroma)
        result = extract_policy_details_sync(pdf_path, llm, prompt_template)
        
        if "error" in result:
            print(f"Extraction failed: {result['error']}")
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
        print(f"  >> Saving structured data to ChromaDB with payer metadata...")
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
            print(f"Successfully stored policy for {payer_name} in ChromaDB")
            
            # --- SAVE TO JSON CACHING ("THE CODE") ---
            save_to_json_cache(result, pdf_file)
            
        except Exception as e:
            print(f"  ERROR Error during add_texts: {e}")


def save_to_json_cache(result: dict, filename: str):
    """Save/Update the structured rules in the persistent JSON cache."""
    print(f"DEBUG: RULES_JSON_PATH = {RULES_JSON_PATH}")
    try:
        rules = []
        if os.path.exists(RULES_JSON_PATH):
            with open(RULES_JSON_PATH, "r", encoding="utf-8") as f:
                rules = json.load(f)
        
        # Check if already in JSON
        existing_index = -1
        for i, r in enumerate(rules):
            if r.get("file") == filename:
                existing_index = i
                break
        
        if existing_index >= 0:
            rules[existing_index] = result
            print(f"Updated JSON cache for {filename}")
        else:
            rules.append(result)
            print(f"Added {filename} to JSON cache")
            
        with open(RULES_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(rules, f, indent=4)
            
    except Exception as e:
        print(f"Failed to update JSON cache: {e}")


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
    
    # Process policies in the base policy directory first
    print("\nScanning base policy directory...")
    ingest_policies_for_payer(policy_base_dir, "General", vectorstore, llm, prompt_template)
    
    # Process each payer subdirectory
    for dir_name, payer_name in PAYER_DIRECTORY_MAP.items():
        payer_dir = os.path.join(policy_base_dir, dir_name)
        ingest_policies_for_payer(payer_dir, payer_name, vectorstore, llm, prompt_template)
    
    print(f"\n{'='*60}")
    print("OK Policy ingestion completed!")
    print(f"{'='*60}")

if __name__ == "__main__":
    ingest_structured_policy_sync()
