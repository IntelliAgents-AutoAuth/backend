import os
import json
import asyncio
import hashlib
import logging
from typing import List, Dict, Any
from pypdf import PdfReader
from pathlib import Path

# Fix relative imports for standalone or module usage
import sys
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from utils.llm_util import RobustLLM
from utils.cache_manager import pdf_cache
from prompts.pdf_summarization_prompts import get_pdf_summarization_prompt

logger = logging.getLogger(__name__)

async def get_file_hash(file_path: str) -> str:
    """Generate a SHA-256 hash of the file content for reliable caching."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read in chunks to handle large files
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

async def summarize_single_pdf(pdf_path: str, llm, prompt_template) -> Dict[str, Any]:
    """
    Summarize a single PDF with caching.
    Check cache first, then extract text and call LLM.
    """
    file_name = os.path.basename(pdf_path)
    
    try:
        # 1. Cache Check (Hash-based)
        file_hash = await get_file_hash(pdf_path)
        cache_key = f"summary_v1_{file_hash}"
        cached_summary = pdf_cache.get(cache_key)
        
        if cached_summary:
            logger.info(f"[summarization_service] Cache HIT for {file_name}")
            return {"file": file_name, "summary": cached_summary, "cached": True}

        # 2. Extract Text
        logger.info(f"[summarization_service] Extracting text from {file_name}...")
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        
        if not text.strip():
            return {"file": file_name, "summary": "No extractable text found.", "error": "Empty text"}

        # 3. LLM Summarization
        logger.info(f"[summarization_service] Sending {file_name} to LLM for summarization...")
        prompt = prompt_template.invoke({"document_text": text})
        response = await llm.ainvoke(prompt)
        summary = response.content if hasattr(response, "content") else str(response)
        
        # 4. Save to Cache
        pdf_cache.set(cache_key, summary)
        
        return {
            "file": file_name,
            "summary": summary,
            "cached": False
        }
    except Exception as e:
        logger.error(f"[summarization_service] Error processing {file_name}: {e}")
        return {"file": file_name, "error": str(e)}

async def summarize_case_documents(case_id: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Summarize all PDFs for a specific case concurrently.
    
    Args:
        case_id: The case identifier
        force_refresh: If True, bypass existing case-level summary file (but still use individual file cache)
    
    Returns:
        List of summary results
    """
    target_dir = os.path.join(backend_dir, "uploads", case_id)
    output_file = os.path.join(backend_dir, "uploads", f"{case_id}_summaries.json")
    
    if not os.path.exists(target_dir):
        logger.warning(f"[summarization_service] No upload directory found for case {case_id}")
        return []

    # Find all PDFs
    pdf_files = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.lower().endswith('.pdf')]
    if not pdf_files:
        logger.info(f"[summarization_service] No PDFs found for case {case_id}")
        return []

    logger.info(f"[summarization_service] Processing {len(pdf_files)} documents for case {case_id}...")
    
    # Initialize LLM and Prompt
    llm = RobustLLM.get_llm_for_task(task="summarization")
    if not llm:
        logger.error("[summarization_service] Failed to initialize LLM.")
        return []

    prompt_template = get_pdf_summarization_prompt()

    # Create tasks for parallel execution
    tasks = [summarize_single_pdf(pdf, llm, prompt_template) for pdf in pdf_files]
    
    # Run all tasks concurrently using asyncio.gather
    results = await asyncio.gather(*tasks)

    # Save aggregate results to the case-specific JSON file
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=4)
        logger.info(f"[summarization_service] Aggregated summaries saved to {output_file}")
    except Exception as e:
        logger.error(f"[summarization_service] Failed to save aggregated summaries: {e}")

    return results

if __name__ == "__main__":
    # Test run
    logging.basicConfig(level=logging.INFO)
    asyncio.run(summarize_case_documents("PA-20260318-00006"))
