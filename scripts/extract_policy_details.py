import os
import sys
import json
import asyncio
from pypdf import PdfReader

# Add backend directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(backend_dir)

from utils.llm_util import RobustLLM
from prompts.policy_extraction_prompts import get_policy_extraction_prompt

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

async def extract_policy_details(pdf_path: str, llm, prompt_template) -> dict:
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
        
        print(f"Sent {os.path.basename(pdf_path)} to Gemini for policy extraction...")
        response = await llm.ainvoke(prompt)
        
        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
            
        return {
            "file": os.path.basename(pdf_path),
            "extracted_data": json.loads(content)
        }
    except Exception as e:
        print(f"Error processing {pdf_path}: {e}")
        return {"file": os.path.basename(pdf_path), "error": str(e), "raw_response": response.content if 'response' in locals() else None}

async def main():
    target_pdf = os.path.join(backend_dir, "policy-pdfs", "aetna", "test_doc.pdf")
    output_file = os.path.join(backend_dir, "policy-pdfs", "extracted_policy_rules.json")

    if not os.path.exists(target_pdf):
        print(f"File not found: {target_pdf}")
        # Try the other one if test_doc.pdf missing
        target_pdf = os.path.join(backend_dir, "policy-pdfs", "aetna", "officelink-updates-october-2025-olu.pdf")
        if not os.path.exists(target_pdf):
            return

    llm = RobustLLM.get_llm_for_task(task="policy_extraction")
    if not llm:
        print("Failed to initialize LLM.")
        return

    prompt_template = get_policy_extraction_prompt()

    result = await extract_policy_details(target_pdf, llm, prompt_template)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump([result], f, indent=4)
        
    print(f"Successfully extracted policy details.")
    print(f"Output saved to {output_file}")
    
    input("\n[observability] Traces sent to Phoenix. Press Enter to exit and close the local script...")

if __name__ == "__main__":
    asyncio.run(main())
