import pypdfium2 as pdfium
import torch
import json
import re
import os
from transformers import BertTokenizer, BertForSequenceClassification
from datetime import datetime

# Path relative to this script: agents/section_finder_model
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "section_finder_model")
MAX_LENGTH = 256
THRESHOLD  = 0.75

DOC_MAPPING = {
    "clinical_justification_note": [
        "clinical notes", "clinical documentation",
        "letter of medical necessity", "medical necessity",
        "physician statement", "physician attestation",
        "physician notes", "treating physician notes",
        "attending physician notes", "clinical justification",
        "supporting documentation", "physician letter"
    ],
    "echocardiogram_report": [
        "echocardiogram", "echo report", "cardiac echo",
        "transthoracic echo", "tte", "cardiac ultrasound",
        "cardiac imaging report", "ejection fraction",
        "lvef", "echocardiographic"
    ],
    "prior_treatment_records": [
        "prior treatment", "treatment history",
        "failed treatment", "conservative treatment",
        "previous therapy", "treatment failure",
        "prior therapy", "medication trial",
        "failed medication", "prior medication"
    ],
    "physician_order": [
        "physician order", "ordering physician",
        "physician referral", "referral form",
        "order form", "prescription",
        "provider order", "physician authorization"
    ],
    "lab_results": [
        "lab results", "laboratory results",
        "blood work", "hba1c", "hemoglobin a1c",
        "bnp", "troponin", "lab values",
        "laboratory findings", "diagnostic lab",
        "blood test"
    ],
    "imaging_report": [
        "imaging report", "radiology report",
        "x-ray report", "xray", "mri report",
        "ct scan", "prior imaging", "radiological"
    ],
    "physical_therapy_records": [
        "physical therapy", "physiotherapy",
        "pt records", "rehabilitation",
        "therapy notes", "therapy records"
    ],
    "specialist_consultation": [
        "specialist consultation", "cardiology consultation",
        "neurology consultation", "consultation note",
        "specialist report", "specialist note"
    ],
    "diagnosis_documentation": [
        "icd-10", "icd10", "diagnosis code",
        "confirmed diagnosis", "diagnosis documentation"
    ],
    "medication_history": [
        "medication history", "drug history",
        "medication list", "current medications",
        "medication records"
    ]
}

print("🔄 Loading section finder model...")
tokenizer = BertTokenizer.from_pretrained(MODEL_PATH)
model     = BertForSequenceClassification.from_pretrained(MODEL_PATH)
model.eval()
print("✅ Model loaded!\n")


def extract_paragraphs(pdf_input) -> list:
    all_paragraphs = []
    pdf = pdfium.PdfDocument(pdf_input)
    try:
        num_pages = len(pdf)
        
        for i in range(num_pages):
            page = pdf.get_page(i)
            # Load textpage to extract text
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            
            if text:
                # Split on empty lines, bullet points, or dashes
                paras = re.split(r'\n\s*\n|\n•|\n-', text)
                filtered_paras = [p.strip() for p in paras if len(p.strip()) > 30]
                all_paragraphs.extend(filtered_paras)
            
            if (i + 1) % 100 == 0 or (i + 1) == num_pages:
                print(f"   Page {i+1}/{num_pages} processed")
    finally:
        pdf.close()
            
    return all_paragraphs


def is_required_section(text: str) -> dict:
    inputs = tokenizer(
        text,
        truncation=True,
        padding="max_length",
        max_length=MAX_LENGTH,
        return_tensors="pt"
    )
    with torch.no_grad():
        outputs = model(**inputs)
    probs      = torch.softmax(outputs.logits, dim=1)[0]
    pred_id    = torch.argmax(probs).item()
    confidence = round(probs[pred_id].item(), 4)
    return {"is_required": pred_id == 1, "confidence": confidence}


def extract_doc_names(paragraph: str) -> list:
    text_lower = paragraph.lower()
    found_docs = []
    for doc_name, keywords in DOC_MAPPING.items():
        for keyword in keywords:
            if keyword in text_lower:
                if doc_name not in found_docs:
                    found_docs.append(doc_name)
                break
    return found_docs


def pdf_policy_agent(pdf_input) -> dict:
    print("\n" + "=" * 60)
    print("  PDF POLICY AGENT")
    print("=" * 60)
    
    input_desc = pdf_input if isinstance(pdf_input, str) else "Uploaded Binary Data"
    print(f"  Input: {input_desc}\n")

    print("📄 Extracting and splitting text from PDF (fast)...")
    paragraphs = extract_paragraphs(pdf_input)
    print(f"   Found {len(paragraphs)} paragraphs")

    print("\n🔍 Scanning paragraphs with model...")
    required_paragraphs = []
    all_required_docs   = []

    for i, para in enumerate(paragraphs):
        result = is_required_section(para)
        if result["is_required"] and result["confidence"] >= THRESHOLD:
            print(f"   ✅ Paragraph {i+1} — REQUIRED "
                  f"(conf: {result['confidence']})")
            doc_names = extract_doc_names(para)
            required_paragraphs.append({
                "paragraph_index": i + 1,
                "confidence":      result["confidence"],
                "text":            para[:200],
                "docs_found":      doc_names
            })
            for doc in doc_names:
                if doc not in all_required_docs:
                    all_required_docs.append(doc)

    result = {
        "status":                  "success",
        "input_source":            pdf_input if isinstance(pdf_input, str) else "bytes_stream",
        "total_paragraphs":        len(paragraphs),
        "required_sections_found": len(required_paragraphs),
        "required_documents":      all_required_docs,
        "section_details":         required_paragraphs,
        "extracted_at":            datetime.utcnow().isoformat()
    }

    print("\n" + "=" * 60)
    print("  EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"  Paragraphs scanned : {len(paragraphs)}")
    print(f"  Required sections  : {len(required_paragraphs)}")
    print(f"  Documents found    : {len(all_required_docs)}")
    print("\n  Required Documents:")
    for doc in all_required_docs:
        print(f"    ✅ {doc}")

    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        result = pdf_policy_agent(sys.argv[1])
        print("\n📄 Full Result:")
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python pdf_policy_agent.py your_policy.pdf")
