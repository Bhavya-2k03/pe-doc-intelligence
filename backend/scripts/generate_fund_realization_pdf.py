"""
Regenerate FUND_REALIZATION_Q3_2025.pdf (side_letter_flow / deferral scenario).

Two fixes over the original seed PDF:

  1. The metrics were laid out as dotted-leader text
     ("Total Fund Commitments ....... $50,000,000"), not a real table. The
     parser inferred a table from the visual alignment rather than reading
     one. This emits an actual PDF table object.

  2. The original literally contained "Reporting Period: Q, 2025" — the "3"
     was missing from the source text layer. (Baseline LlamaParse hid this by
     inferring "Q3" from the title; a parser filling in a character the
     document does not contain is exactly what this system should not rely
     on.) Corrected to "Q3 2025".

Values, dates and wording are otherwise unchanged, so scenario outcomes and
the deferral gate's 13%-realization input stay identical.

Writes to backend/files/ (the push_packages source dir), replacing the
existing file under the same name so the DB reference stays valid.

Run from backend/: python scripts/generate_fund_realization_pdf.py
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

OUT_PATH = Path(__file__).resolve().parent.parent / "files" / "FUND_REALIZATION_Q3_2025.pdf"

# Column header names the entity. In the original dotted-leader version the
# parser promoted "Total Fund Commitments" to the header row, so every data
# row happened to sit under a header containing "Fund" — an accidental scope
# anchor. A neutral "Metric" header removed it and rows without their own
# entity noun ("Total Invested Capital", "Cumulative Realized Proceeds")
# started dropping ~20% of the time. Naming the entity here and in the
# section heading below makes that anchor explicit rather than incidental.
METRICS = [
    ["Fund Metric", "Amount"],
    ["Total Fund Commitments", "$50,000,000"],
    ["Total Invested Capital", "$19,500,000"],
    ["Cumulative Realized Proceeds", "$6,500,000"],
    ["Fund Realization Percentage", "13%"],
]


def build():
    doc = SimpleDocTemplate(
        str(OUT_PATH),
        pagesize=letter,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        title="Q3 2025 Fund Realization Report",
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10.5, leading=15)

    el = [
        Paragraph("Q3 2025 FUND REALIZATION REPORT", styles["Title"]),
        Paragraph("10X GROWTH FUND, L.P.", styles["Heading2"]),
        Spacer(1, 0.2 * inch),
        Paragraph("<b>Report Date:</b> October 12, 2025", body),
        # "Q3 2025" — the original seed PDF was missing the "3" here.
        Paragraph("<b>Reporting Period:</b> Q3 2025", body),
        Spacer(1, 0.12 * inch),
        Paragraph("<b>To:</b> All Limited Partners", body),
        Paragraph("<b>From:</b> General Partner", body),
        Spacer(1, 0.25 * inch),
        # Heading names the entity, giving scope resolution a Layer 2a anchor
        # for table rows that carry no entity noun of their own.
        Paragraph("FUND PERFORMANCE SUMMARY", styles["Heading3"]),
        Paragraph(
            "As of the reporting date, the Fund has achieved the following "
            "performance metrics:", body),
        Spacer(1, 0.18 * inch),
    ]

    t = Table(METRICS, colWidths=[3.4 * inch, 2.2 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.black),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    el.append(t)

    el += [
        Spacer(1, 0.25 * inch),
        Paragraph(
            "The Fund Realization Percentage is calculated as the cumulative "
            "distributions made to Limited Partners divided by total aggregate "
            "capital commitments of the Fund.", body),
        Spacer(1, 0.35 * inch),
        Paragraph("Sincerely,", body),
        Paragraph("General Partner", body),
        Paragraph("10x Growth Fund, L.P.", body),
    ]

    doc.build(el)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    build()
