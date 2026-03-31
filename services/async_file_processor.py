"""
Async File Processor Service

Parallel PDF/document extraction with concurrent text extraction.
Optimized for bulk file uploads to maximize throughput.

OPTIMIZATION 6: Parallel file extraction for multiple uploads
- Extract multiple PDFs concurrently (max 5 concurrent)
- Process PDF pages in parallel batches
- Avoid blocking on CPU-intensive text extraction
"""

import asyncio
import os
from pathlib import Path
from pypdf import PdfReader
from typing import Dict, List


class AsyncFileExtractor:
    """Parallel PDF/document extraction with concurrent text extraction."""
    
    def __init__(self, max_concurrency: int = 5):
        """
        Initialize extractor with concurrency limit.
        
        Args:
            max_concurrency: Maximum concurrent file extractions (default: 5)
        """
        self.max_concurrency = max_concurrency
    
    async def extract_text_from_file(self, file_path: str, max_page_concurrency: int = 3) -> str:
        """
        Extract text from PDF with async page processing.
        
        Args:
            file_path: Path to PDF file
            max_page_concurrency: Max concurrent page extractions per PDF
        
        Returns:
            Extracted text from all pages
        """
        try:
            reader = PdfReader(file_path)
            page_count = len(reader.pages)
            
            if page_count == 0:
                return ""
            
            # Create tasks for all pages
            tasks = [
                self._extract_page_async(reader, idx)
                for idx in range(page_count)
            ]
            
            # Limit concurrency with semaphore to avoid memory spike
            semaphore = asyncio.Semaphore(max_page_concurrency)
            
            async def bounded_task(task):
                async with semaphore:
                    return await task
            
            results = await asyncio.gather(*[bounded_task(t) for t in tasks])
            extracted_text = "\n".join(filter(None, results))
            
            print(f"[async_processor] Extracted {page_count} pages from {os.path.basename(file_path)}")
            return extracted_text
            
        except Exception as e:
            print(f"[async_processor] Error extracting {file_path}: {e}")
            return ""
    
    async def _extract_page_async(self, reader: PdfReader, page_idx: int) -> str:
        """
        Extract text from single PDF page (run CPU-bound work in executor).
        
        Args:
            reader: PdfReader instance
            page_idx: Index of page to extract
        
        Returns:
            Extracted text or empty string if failed
        """
        loop = asyncio.get_event_loop()
        try:
            text = await loop.run_in_executor(None, reader.pages[page_idx].extract_text)
            return text or ""
        except Exception as e:
            print(f"[async_processor] Error extracting page {page_idx}: {e}")
            return ""
    
    async def extract_multiple_files(self, file_paths: List[str]) -> Dict[str, str]:
        """
        Extract text from multiple files concurrently.
        
        Args:
            file_paths: List of file paths to extract
        
        Returns:
            Dictionary mapping file_path -> extracted_text
        """
        # Limit total concurrent extractions with outer semaphore
        semaphore = asyncio.Semaphore(self.max_concurrency)
        
        async def bounded_extraction(fpath: str) -> tuple[str, str]:
            async with semaphore:
                text = await self.extract_text_from_file(fpath)
                return fpath, text
        
        tasks = [bounded_extraction(fpath) for fpath in file_paths]
        results = await asyncio.gather(*tasks)
        
        result_dict = {fpath: text for fpath, text in results}
        print(f"[async_processor] Completed extraction for {len(result_dict)} files")
        return result_dict


async def extract_files_batch(file_paths: List[str], max_concurrency: int = 5) -> Dict[str, str]:
    """
    Convenience function for batch file extraction.
    
    Args:
        file_paths: List of file paths to extract
        max_concurrency: Maximum concurrent extractions
    
    Returns:
        Dictionary mapping file_path -> extracted_text
    """
    extractor = AsyncFileExtractor(max_concurrency=max_concurrency)
    return await extractor.extract_multiple_files(file_paths)
