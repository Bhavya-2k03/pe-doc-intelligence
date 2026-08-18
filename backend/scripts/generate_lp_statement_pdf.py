"""
Generate a REALISTIC single-LP capital account statement with a
period-column table — the layout fund administrators actually send to an
individual LP.

Why this file (and not the multi-LP one) is the right test for truefee:
truefee's field registry is scoped to ONE investor
(investor_invested_capital, entity_scope="investor"). A multi-LP roster
table poses a scope-resolution problem the data model doesn't represent.
A single-LP statement is the real document.

The hard part here is NOT parsing — it's column selection. Line items are
rows; reporting periods are columns. The correct value for a field is in
the "as of" column (the LAST one). An extractor that grabs the first
numeric cell in the row silently returns a stale figure from an earlier
quarter — a wrong number that looks perfectly plausible.

Run from backend/: python scripts/generate_lp_statement_pdf.py
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

OUT_PATH = Path(__file__).resolve().parent / "_test_LP_STATEMENT_PERIOD_COLUMNS.pdf"

# Rows = line items, Columns = reporting periods. Current period is the LAST column.
TABLE_DATA = [
    ["Line Item", "Q1 2025", "Q2 2025", "Q3 2025"],
    ["Committed Capital", "$10,000,000", "$10,000,000", "$10,000,000"],
    ["Cumulative Capital Called", "$5,200,000", "$6,400,000", "$7,300,000"],
    ["Invested Capital (cost basis)", "$4,900,000", "$6,050,000", "$6,850,000"],
    ["Cumulative Distributions", "$700,000", "$1,150,000", "$1,780,000"],
    ["Unfunded Commitment", "$4,800,000", "$3,600,000", "$2,700,000"],
    ["Ending Capital Account (NAV)", "$5,010,000", "$6,220,000", "$7,090,000"],
]


def build():
    doc = SimpleDocTemplate(
        str(OUT_PATH),
        pagesize=letter,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("10x Growth Fund, L.P.", styles["Title"]))
    elements.append(Paragraph("Limited Partner Capital Account Statement", styles["Heading2"]))
    elements.append(Spacer(1, 0.12 * inch))

    for line in [
        "<b>Limited Partner:</b> Limited Partner Y",
        "<b>Statement Date:</b> October 15, 2025",
        "<b>Reporting Period End (As of Date):</b> September 30, 2025",
    ]:
        elements.append(Paragraph(line, styles["Normal"]))
    elements.append(Spacer(1, 0.25 * inch))

    col_widths = [2.4 * inch, 1.35 * inch, 1.35 * inch, 1.35 * inch]
    t = Table(TABLE_DATA, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (1, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.black),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(t)

    elements.append(Spacer(1, 0.25 * inch))
    elements.append(Paragraph(
        "All figures are presented on an inception-to-date basis as of the reporting "
        "period end date shown above. Prior period columns are provided for "
        "comparative purposes only.",
        styles["Normal"],
    ))

    doc.build(elements)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    build()
