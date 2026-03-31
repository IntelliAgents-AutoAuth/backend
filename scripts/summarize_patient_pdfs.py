import os
import sys
import json
import asyncio
from pypdf import PdfReader
from pathlib import Path

# Add backend directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(backend_dir)

from utils.llm_util import RobustLLM
from prompts.pdf_summarization_prompts import get_pdf_summarization_prompt

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

import argparse

async def summarize_pdf(pdf_path: str, llm, prompt_template) -> dict:
    print(f"Reading {pdf_path}...")
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        
        if not text.strip():
            return {"file": os.path.basename(pdf_path), "summary": "No extractable text found."}

        prompt = prompt_template.invoke({"document_text": text})
        
        print(f"Sent {os.path.basename(pdf_path)} to Gemini for summarization...")
        response = await llm.ainvoke(prompt)
        
        return {
            "file": os.path.basename(pdf_path),
            "summary": response.content
        }
    except Exception as e:
        print(f"Error processing {pdf_path}: {e}")
        return {"file": os.path.basename(pdf_path), "error": str(e)}

async def main():
    parser = argparse.ArgumentParser(description="Summarize patient PDFs for a specific case.")
    parser.add_argument("--case_id", type=str, default="PA-20260318-00006", help="The case identifier (e.g. PA-20260318-00006)")
    args = parser.parse_args()
    
    case_id = args.case_id
    target_dir = os.path.join(backend_dir, "uploads", case_id)
    
    # Case-specific output file to ensure isolation
    output_file = os.path.join(backend_dir, "uploads", f"{case_id}_summaries.json")
    # Also maintain the global file for backward compatibility if using the default case
    global_output_file = os.path.join(backend_dir, "uploads", "all_summarized_data.json")

    if not os.path.exists(target_dir):
        print(f"Directory not found: {target_dir}")
        return

    pdf_files = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print(f"No PDFs found in {target_dir}")
        return

    print(f"Found {len(pdf_files)} PDFs for case {case_id}. Start concurrent summarization...")
    
    llm = RobustLLM.get_llm_for_task(task="summarization")
    if not llm:
        print("Failed to initialize LLM.")
        return

    prompt_template = get_pdf_summarization_prompt()

    # Create tasks for all pdfs
    tasks = [summarize_pdf(pdf, llm, prompt_template) for pdf in pdf_files]
    
    # Run all tasks concurrently
    results = await asyncio.gather(*tasks)

    # Save to case-specific output
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4)
    
    # Legacy support: also update the global file if we're running the default case
    if case_id == "PA-20260318-00006":
        with open(global_output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=4)
        print(f"Legacy global file updated: {global_output_file}")
        
    print(f"Successfully summarized {len(results)} PDFs for {case_id}.")
    print(f"Output saved to {output_file}")
    
    # Only wait for input if not running in a script/tool environment (check TTY if possible, or just skip for now)
    # input("\n[observability] Traces sent to Phoenix. Press Enter to exit...")

if __name__ == "__main__":
    asyncio.run(main())
