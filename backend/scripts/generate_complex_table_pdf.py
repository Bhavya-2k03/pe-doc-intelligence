"""
Generate a genuinely complex PDF table (real PDF table object, not visually
aligned text) to battle-test LlamaParse's table extraction beyond the simple
key-value case already confirmed to work.

Complexity deliberately included:
  - Multi-row header with merged (spanned) cells (e.g. "Capital Activity"
    spanning two sub-columns) — the classic hard case for layout-based parsers
  - 6 data columns x 7 rows (6 LPs + a TOTAL row)
  - Mixed formatting: currency, percentage, parentheses for negative/n.m.
  - A TOTAL row that is a footer-style aggregate, not just another data row

Run from backend/: python scripts/generate_complex_table_pdf.py
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

OUT_PATH = Path(__file__).resolve().parent / "_test_LP_CAPITAL_ACCOUNT_STATEMENT.pdf"

HEADER_ROW_1 = ["", "", "Capital Activity (ITD)", "", "Position", "", ""]
HEADER_ROW_2 = [
    "LP Name",
    "Committed\nCapital",
    "Called\nCapital",
    "Distributed",
    "Unfunded\nCommitment",
    "NAV",
    "Net IRR",
]

DATA_ROWS = [
    ["Alpine Retirement Systems", "$12,500,000", "$9,375,000", "$2,100,000", "$3,125,000", "$8,940,000", "14.2%"],
    ["Beacon Family Office", "$6,000,000", "$4,500,000", "$975,000", "$1,500,000", "$4,285,000", "13.8%"],
    ["Crestline University Endowment", "$18,000,000", "$13,050,000", "$3,600,000", "$4,950,000", "$12,180,000", "15.1%"],
    ["Delta Sovereign Wealth Fund", "$25,000,000", "$18,125,000", "$4,500,000", "$6,875,000", "$16,940,000", "14.6%"],
    ["Everstone Pension Trust", "$9,500,000", "$6,935,000", "$1,425,000", "$2,565,000", "$6,590,000", "13.1%"],
    ["Fairmont Insurance Co.", "$4,000,000", "$2,900,000", "(n.m.)", "$1,100,000", "$2,845,000", "(4.3%)"],
    ["TOTAL", "$75,000,000", "$54,885,000", "$12,600,000", "$20,115,000", "$51,780,000", "14.3%"],
]


def build():
    doc = SimpleDocTemplate(
        str(OUT_PATH),
        pagesize=letter,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Meridian Capital Partners III, L.P.", styles["Title"]))
    elements.append(Paragraph("Capital Account Statement — As of September 30, 2025", styles["Heading2"]))
    elements.append(Spacer(1, 0.25 * inch))

    table_data = [HEADER_ROW_1, HEADER_ROW_2] + DATA_ROWS
    col_widths = [1.9 * inch] + [0.92 * inch] * 6

    t = Table(table_data, colWidths=col_widths, repeatRows=2)
    t.setStyle(TableStyle([
        # merged header cells
        ("SPAN", (2, 0), (3, 0)),  # "Capital Activity (ITD)" over Called/Distributed
        ("SPAN", (4, 0), (6, 0)),  # "Position" over Unfunded/NAV/Net IRR
        ("SPAN", (0, 0), (0, 1)),  # LP Name spans both header rows
        ("SPAN", (1, 0), (1, 1)),  # Committed Capital spans both header rows

        ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 1), colors.white),
        ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("LINEBELOW", (0, 1), (-1, 1), 1, colors.black),

        # TOTAL row styled as a footer aggregate
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e5e7eb")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),

        ("ROWBACKGROUNDS", (0, 2), (-1, -2), [colors.white, colors.HexColor("#f9fafb")]),
    ]))

    elements.append(t)
    elements.append(Spacer(1, 0.2 * inch))
    elements.append(Paragraph(
        "Figures reflect inception-to-date (ITD) activity. Net IRR is calculated on a "
        "since-inception basis using daily cash flows. (n.m.) denotes not meaningful.",
        styles["Normal"],
    ))

    doc.build(elements)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    build()
