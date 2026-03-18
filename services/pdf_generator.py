"""
PDF Generator Service

Assembles the complete Prior Authorization PDF package from LLM content + uploaded files.

Sections:
  Page 1     — Cover Letter
  Page 2     — Clinical Summary
  Page 3     — Checklist
  Page 4+    — Attached Documents (merged from uploaded PDFs)
"""

import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)

# ─────────────────────────────────────────
# BRAND COLOURS
# ─────────────────────────────────────────
PRIMARY   = colors.HexColor("#38A3A5")
DARK      = colors.HexColor("#1a1a2e")
LIGHT_BG  = colors.HexColor("#f0fafa")
MET_GREEN = colors.HexColor("#16a34a")
MISS_RED  = colors.HexColor("#dc2626")
GREY      = colors.HexColor("#64748b")


# ─────────────────────────────────────────
# STYLE HELPERS
# ─────────────────────────────────────────

def _styles():
    base = getSampleStyleSheet()
    custom = {
        "title": ParagraphStyle(
            "title", fontSize=20, textColor=PRIMARY,
            spaceAfter=6, fontName="Helvetica-Bold", alignment=TA_LEFT,
        ),
        "section_header": ParagraphStyle(
            "section_header", fontSize=13, textColor=PRIMARY,
            spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold",
        ),
        "body": ParagraphStyle(
            "body", fontSize=10, textColor=DARK,
            leading=16, spaceAfter=6, alignment=TA_JUSTIFY,
        ),
        "meta": ParagraphStyle(
            "meta", fontSize=9, textColor=GREY,
            leading=13, spaceAfter=4,
        ),
        "label": ParagraphStyle(
            "label", fontSize=9, textColor=GREY,
            fontName="Helvetica-Bold", spaceAfter=2,
        ),
        "value": ParagraphStyle(
            "value", fontSize=10, textColor=DARK, spaceAfter=8,
        ),
        "checklist_header": ParagraphStyle(
            "checklist_header", fontSize=10, textColor=colors.white,
            fontName="Helvetica-Bold",
        ),
        "table_cell": ParagraphStyle(
            "table_cell", fontSize=9, textColor=DARK,
            leading=12, spaceBefore=2, spaceAfter=2, alignment=TA_LEFT,
        ),
    }
    return custom


# ─────────────────────────────────────────
# HEADER BANNER  (appears on each page)
# ─────────────────────────────────────────

def _header(canvas, doc):
    canvas.saveState()
    # Top bar
    canvas.setFillColor(PRIMARY)
    canvas.rect(0, letter[1] - 0.6 * inch, letter[0], 0.6 * inch, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 14)
    canvas.drawString(0.5 * inch, letter[1] - 0.4 * inch, "AutoAuth")
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(
        letter[0] - 0.5 * inch, letter[1] - 0.4 * inch,
        f"Prior Authorization Package  |  {datetime.now().strftime('%B %d, %Y')}",
    )
    # Footer
    canvas.setFillColor(GREY)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(0.5 * inch, 0.3 * inch,
                      "CONFIDENTIAL — For Insurance Review Only")
    canvas.drawRightString(
        letter[0] - 0.5 * inch, 0.3 * inch, f"Page {doc.page}",
    )
    canvas.restoreState()


# ─────────────────────────────────────────
# SECTION BUILDERS
# ─────────────────────────────────────────

def _build_cover_letter(story, styles, ehr: dict, cover_letter_text: str):
    s = styles

    story.append(Paragraph("PRIOR AUTHORIZATION REQUEST", s["title"]))
    story.append(Paragraph("Cover Letter", s["section_header"]))
    story.append(HRFlowable(width="100%", color=PRIMARY, thickness=1.5))
    story.append(Spacer(1, 0.15 * inch))

    # Patient info block
    def _p(text): return Paragraph(str(text), s["table_cell"])
    
    info_rows = [
        ["Patient Name",  _p(f"{ehr.get('patient_first_name','')} {ehr.get('patient_last_name','')}").text], # Keep as text for simple keys if needed, but Paragraph is safer for values
        ["Date of Birth",  _p(ehr.get("patient_dob") or ehr.get("date_of_birth", "N/A"))],
        ["Insurance",      _p(ehr.get("payer_name") or ehr.get("insurance_company", "N/A"))],
        ["Member ID",      _p(ehr.get("member_id", "N/A"))],
        ["Policy Number",  _p(ehr.get("policy_number", "N/A"))],
        ["CPT Code",       _p(ehr.get("cpt_code", "N/A"))],
        ["ICD-10",         _p(ehr.get("primary_icd10_code") or ehr.get("icd10_code", "N/A"))],
        ["Physician",      _p(ehr.get("physician_name", "N/A"))],
        ["Physician NPI",  _p(ehr.get("physician_npi", "N/A"))],
        ["Facility",       _p(ehr.get("facility_name", "N/A"))],
        ["Date of Request", _p(datetime.now().strftime("%B %d, %Y"))],
    ]
    
    # Re-wrap labels as Paragraphs for consistency if needed, but labels are usually small
    wrapped_rows = [[_p(row[0]), row[1]] for row in info_rows]
    
    tbl = Table(wrapped_rows, colWidths=[2.0 * inch, 4.5 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_BG),
        ("TEXTCOLOR",  (0, 0), (0, -1), GREY),
        ("FONTNAME",   (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT_BG]),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.2 * inch))

    # LLM letter body
    for para in cover_letter_text.split("\n"):
        if para.strip():
            story.append(Paragraph(para.strip(), s["body"]))
    story.append(PageBreak())


def _build_clinical_summary(story, styles, clinical_summary_text: str):
    s = styles
    story.append(Paragraph("Clinical Summary", s["title"]))
    story.append(HRFlowable(width="100%", color=PRIMARY, thickness=1.5))
    story.append(Spacer(1, 0.15 * inch))

    for line in clinical_summary_text.split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 0.06 * inch))
        elif line.startswith("**") and line.endswith("**"):
            story.append(Paragraph(line.replace("**", ""), s["section_header"]))
        elif line.startswith("#"):
            story.append(Paragraph(line.lstrip("#").strip(), s["section_header"]))
        else:
            story.append(Paragraph(line, s["body"]))

    story.append(PageBreak())


def _build_checklist(story, styles, checklist: list):
    s = styles
    story.append(Paragraph("Requirements Checklist", s["title"]))
    story.append(HRFlowable(width="100%", color=PRIMARY, thickness=1.5))
    story.append(Spacer(1, 0.15 * inch))

    # Header row
    rows = [[
        Paragraph("Requirement", s["checklist_header"]),
        Paragraph("Status", s["checklist_header"]),
        Paragraph("Evidence", s["checklist_header"])
    ]]
    for item in checklist:
        status_text = "✔ MET" if item.get("met") else "✘ MISSING"
        rows.append([
            Paragraph(item.get("item", ""), s["table_cell"]),
            Paragraph(status_text, s["table_cell"]),
            Paragraph(item.get("evidence", ""), s["table_cell"]),
        ])

    tbl = Table(rows, colWidths=[2.4 * inch, 0.9 * inch, 3.2 * inch])
    style_cmds = [
        # Header
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("WORDWRAP",      (0, 0), (-1, -1), True),
    ]
    # Colour-code MET / MISSING cells
    for i, item in enumerate(checklist, start=1):
        colour = MET_GREEN if item.get("met") else MISS_RED
        style_cmds.append(("TEXTCOLOR", (1, i), (1, i), colour))
        style_cmds.append(("FONTNAME",  (1, i), (1, i), "Helvetica-Bold"))
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), LIGHT_BG))

    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)
    story.append(PageBreak())


def _build_attached_docs(story, styles, uploaded_file_paths: List[str]):
    """Adds a cover page for attached docs; merging happens via pypdf after."""
    s = styles
    story.append(Paragraph("Attached Documents", s["title"]))
    story.append(HRFlowable(width="100%", color=PRIMARY, thickness=1.5))
    story.append(Spacer(1, 0.15 * inch))

    if not uploaded_file_paths:
        story.append(Paragraph("No additional documents were uploaded for this case.", s["body"]))
        return

    story.append(Paragraph("The following documents are attached to this package:", s["body"]))
    story.append(Spacer(1, 0.1 * inch))

    rows = [[
        Paragraph("#", s["checklist_header"]),
        Paragraph("Document Name", s["checklist_header"]),
        Paragraph("File", s["checklist_header"])
    ]]
    for i, path in enumerate(uploaded_file_paths, 1):
        rows.append([
            Paragraph(str(i), s["table_cell"]),
            Paragraph(Path(path).stem.replace("_", " ").title(), s["table_cell"]),
            Paragraph(Path(path).name, s["table_cell"])
        ])

    tbl = Table(rows, colWidths=[0.4 * inch, 3.5 * inch, 2.6 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("ROWBACKGROUNDS", (1, 0), (-1, -1), [colors.white, LIGHT_BG]),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tbl)


# ─────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────

def generate_pa_pdf(
    case_id: str,
    content: dict,
    uploaded_file_paths: Optional[List[str]] = None,
    output_dir: Optional[str] = None,
) -> str:
    """
    Build and return the path to the generated PA package PDF.

    Args:
        case_id:             Used for the output filename.
        content:             Dict from pa_document_agent.generate_pa_content().
                             Keys: ehr, cover_letter, clinical_summary, checklist
        uploaded_file_paths: List of absolute paths to uploaded PDFs to attach.
        output_dir:          Directory to save the PDF. Defaults to uploads/generated/.

    Returns:
        Absolute path to the generated PDF.
    """
    if uploaded_file_paths is None:
        uploaded_file_paths = []

    # Resolve output directory
    if not output_dir:
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(backend_dir, "uploads", "generated")
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_path = os.path.join(output_dir, f"PA_{case_id}_{timestamp}.pdf")

    # Build story
    styles = _styles()
    story = []

    _build_cover_letter(story, styles, content.get("ehr", {}), content.get("cover_letter", ""))
    _build_clinical_summary(story, styles, content.get("clinical_summary", ""))
    _build_checklist(story, styles, content.get("checklist", []))
    _build_attached_docs(story, styles, uploaded_file_paths)

    # Render main PDF
    doc = SimpleDocTemplate(
        base_path,
        pagesize=letter,
        topMargin=0.9 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    doc.build(story, onFirstPage=_header, onLaterPages=_header)

    # Merge uploaded PDFs (if any)
    pdf_attachments = [p for p in uploaded_file_paths if p.lower().endswith(".pdf") and os.path.exists(p)]
    if pdf_attachments:
        try:
            from pypdf import PdfWriter, PdfReader
            writer = PdfWriter()

            # Add main document pages
            for page in PdfReader(base_path).pages:
                writer.add_page(page)

            # Append each attachment
            for attach_path in pdf_attachments:
                reader = PdfReader(attach_path)
                for page in reader.pages:
                    writer.add_page(page)

            merged_path = base_path.replace(".pdf", "_merged.pdf")
            with open(merged_path, "wb") as f:
                writer.write(f)

            os.replace(merged_path, base_path)
            print(f"[pdf_generator] Merged {len(pdf_attachments)} attachment(s) into PDF.")
        except Exception as e:
            print(f"[pdf_generator] PDF merge failed (attachments not included): {e}")

    print(f"[pdf_generator] PDF saved to: {base_path}")
    return base_path
