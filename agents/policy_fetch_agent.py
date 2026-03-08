import pdfplumber
import pypdfium2 as pdfium
import json
import os
import logging

# ── Suppress noisy FontBBox warnings from pdfminer ──
logging.getLogger("pdfminer").setLevel(logging.ERROR)

def extract_pdf(pdf_path, payer, policy_name, year, use_fast_mode=False):
    """
    Extracts text from a PDF.
    
    Args:
        pdf_path: Path to the PDF file.
        payer: Name of the payer.
        policy_name: Name of the policy.
        year: Year of the policy.
        use_fast_mode: If True, uses pypdfium2 (very fast). If False, uses pdfplumber (accurate for tables).
    """
    try:
        full_text = ""
        if use_fast_mode:
            # High-speed extraction (recommended for 100+ pages)
            pdf = pdfium.PdfDocument(pdf_path)
            for page in pdf:
                text_page = page.get_textpage()
                text = text_page.get_text_range()
                if text:
                    full_text += text
        else:
            # High-precision extraction (slower, better for tables/layout)
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text += text
                        
        return {
            "payer": payer,
            "policy_name": policy_name,
            "year": year,
            "source_file": pdf_path,
            "text": full_text
        }
    except Exception as e:
        print(f"❌ Error reading {pdf_path}: {e}")
        return None

pdfs = [
    # United Healthcare
    {
        "path": "policy-pdfs/united-healthcare/UHC-Commercial-Advance-Notification-PA-Requirements-1-1-2025.pdf",
        "payer": "United Healthcare",
        "policy": "Commercial PA Requirements",
        "year": 2025
    },
    {
        "path": "policy-pdfs/united-healthcare/UHCCP-Rad-Card-Guidelines-May-2026.pdf",
        "payer": "United Healthcare",
        "policy": "Cardiology Radiology Imaging Guidelines",
        "year": 2026
    },
    {
        "path": "policy-pdfs/united-healthcare/UN-CSRAD003OH-E-Adult-Cardiac-02-2026.pdf",
        "payer": "United Healthcare",
        "policy": "Adult Cardiac Imaging Guidelines Ohio",
        "year": 2026
    },

    # Aetna
    {
        "path": "policy-pdfs/aetna/officelink-updates-october-2025-olu.pdf",
        "payer": "Aetna",
        "policy": "OfficeLink Updates October 2025",
        "year": 2025
    },

    # Cigna
    {
        "path": "policy-pdfs/cigna/Cigna_Cardiac Imaging Guidelines_V1.0.2026_eff02.03.2026_PUB10.29.2025.pdf",
        "payer": "Cigna",
        "policy": "Cardiac Imaging Guidelines V1 2026",
        "year": 2026
    },

    # Humana
    {
        "path": "policy-pdfs/humana/SC_Medicaid_Cardiac_Devicespdf.pdf",
        "payer": "Humana",
        "policy": "Cardiac Devices SC Medicaid",
        "year": 2025
    },
    {
        "path": "policy-pdfs/humana/2026 Medicare Prior Authorization Listpdf.pdf",
        "payer": "Humana",
        "policy": "Medicare Advantage PA List",
        "year": 2026
    },

    # BCBS
    {
        "path": "policy-pdfs/bcbs/commercial-fi-certain-aso-prior-auth-services-2025.pdf",
        "payer": "Blue Cross Blue Shield Texas",
        "policy": "Prior Authorization Services",
        "year": 2025
    },

    # CMS
    {
        "path": "policy-pdfs/cms/lca_cardiac_radionuclide_imaging_jan_2020_l33457.pdf",
        "payer": "CMS Medicare",
        "policy": "LCD Cardiac Radionuclide Imaging",
        "year": 2019
    },
]

# ── Run extraction ──
all_extracted = []

for pdf_info in pdfs:
    print(f"Processing: {pdf_info['path']}")
    
    # Auto-detect if we should use fast mode based on file size/complexity
    # (Assuming we want accuracy by default unless it's huge)
    use_fast = False
    if os.path.exists(pdf_info["path"]):
        file_size_mb = os.path.getsize(pdf_info["path"]) / (1024 * 1024)
        if file_size_mb > 5:  # If larger than 5MB, use fast mode
            use_fast = True
            print(f"   ⚡ Large file detected ({file_size_mb:.2f}MB). Using Fast Mode.")

    result = extract_pdf(
        pdf_info["path"],
        pdf_info["payer"],
        pdf_info["policy"],
        pdf_info["year"],
        use_fast_mode=use_fast
    )
    if result:
        all_extracted.append(result)
        print(f"✅ Done: {pdf_info['path']}")
    else:
        print(f"❌ Skipped: {pdf_info['path']}")

# ── Save results ──
os.makedirs("extracted-data", exist_ok=True)
with open("extracted-data/all_policies.json", "w", encoding="utf-8") as f:
    json.dump(all_extracted, f, indent=2, ensure_ascii=False)

print(f"\n✅ Extraction complete!")
print(f"✅ {len(all_extracted)} policies extracted")
print(f"✅ Saved to extracted-data/all_policies.json")