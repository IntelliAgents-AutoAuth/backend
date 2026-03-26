"""PDF extractor utility.

This module provides a simple helper to extract raw text from PDFs using pdfplumber.

No LLM calls are performed here; this is purely local text extraction.
"""

from __future__ import annotations

import os

from langchain_core.tools import tool
from typing import Optional


def extract_raw_text(pdf_path: str) -> str:
    """Extract raw text from a PDF.

    Args:
        pdf_path: Path to a PDF file.

    Returns:
        The full concatenated raw text from all pages.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
        RuntimeError: If extraction fails (e.g. missing dependency or corrupt PDF).
    """

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Compute MD5 hash of the PDF file to use as a cache key
    import hashlib
    with open(pdf_path, "rb") as f:
        file_hash = hashlib.md5(f.read()).hexdigest()

    # Determine cache directory and file path
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    cache_dir = os.path.join(backend_dir, ".cache", "pdf_texts")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{file_hash}.txt")

    # Return cached text if it exists
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"Warning: Failed to read cache {cache_file}: {e}")

    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError(
            "pdfplumber is required to extract PDF text. Install it with `pip install pdfplumber`."
        ) from exc

    try:
        with pdfplumber.open(pdf_path) as pdf:
            texts: list[str] = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                texts.append(text)

        full_text = "\n\n".join(texts)

        # Save to cache
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(full_text)
        except Exception as e:
            print(f"Warning: Failed to write to cache {cache_file}: {e}")

        return full_text

    except Exception as exc:
        raise RuntimeError(f"Failed to extract text from PDF: {exc}") from exc

# Tool for use in LangChain agents
pdf_extractor = tool(extract_raw_text)
