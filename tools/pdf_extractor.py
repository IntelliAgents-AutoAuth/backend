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

        return "\n\n".join(texts)

    except Exception as exc:
        raise RuntimeError(f"Failed to extract text from PDF: {exc}") from exc

# Tool for use in LangChain agents
pdf_extractor = tool(extract_raw_text)
