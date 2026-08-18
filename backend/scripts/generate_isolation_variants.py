"""
Isolate WHY the period-column LP statement extracted zero fields.

Two competing hypotheses, one variant each:

  Variant A — SINGLE period column, competing scope KEPT.
      Tests the multi-column hypothesis. If A extracts, multi-column
      selection is the culprit.

  Variant B — THREE period columns, competing scope REMOVED
      (no fund H1 title; document framed purely as the LP's statement).
      Tests the scope hypothesis. If B extracts, competing scope
      (Layer 2b -> Layer 5 omit) is the culprit.

Run from backend/: python scripts/generate_isolation_variants.py
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

HERE = Path(__file__).resolve().parent

ROWS_ALL = [
    ["Committed Capital", "$10,000,000", "$10,000,000", "$10,000,000"],
    ["Cumulative Capital Called", "$5,200,000", "$6,400,000", "$7,300,000"],
    ["Invested Capital (cost basis)", "$4,900,000", "$6,050,000", "$6,850,000"],
    ["Cumulative Distributions", "$700,000", "$1,150,000", "$1,780,000"],
    ["Unfunded Commitment", "$4,800,000", "$3,600,000", "$2,700,000"],
    ["Ending Capital Account (NAV)", "$5,010,000", "$6,220,000", "$7,090,000"],
]


def _table(data, col_widths):
    t = Table(data, colWidths=col_widths, repeatRows=1)
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
    return t


def build_variant_a():
    """Single column (Q3 only). Competing scope KEPT (fund H1 title present)."""
    out = HERE / "_iso_A_single_column.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=letter,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch)
    s = getSampleStyleSheet()
    el = [
        Paragraph("10x Growth Fund, L.P.", s["Title"]),
        Paragraph("Limited Partner Capital Account Statement", s["Heading2"]),
        Spacer(1, 0.12 * inch),
        Paragraph("<b>Limited Partner:</b> Limited Partner Y", s["Normal"]),
        Paragraph("<b>Statement Date:</b> October 15, 2025", s["Normal"]),
        Paragraph("<b>Reporting Period End (As of Date):</b> September 30, 2025", s["Normal"]),
        Spacer(1, 0.25 * inch),
    ]
    data = [["Line Item", "Q3 2025"]] + [[r[0], r[3]] for r in ROWS_ALL]
    el.append(_table(data, [2.8 * inch, 1.6 * inch]))
    el.append(Spacer(1, 0.25 * inch))
    el.append(Paragraph(
        "All figures are presented on an inception-to-date basis as of the "
        "reporting period end date shown above.", s["Normal"]))
    doc.build(el)
    print(f"Wrote {out.name}")


def build_variant_b():
    """Three columns. Competing scope REMOVED — no fund H1, LP-only framing."""
    out = HERE / "_iso_B_no_competing_scope.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=letter,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch)
    s = getSampleStyleSheet()
    el = [
        Paragraph("Capital Account Statement for Limited Partner Y", s["Title"]),
        Spacer(1, 0.12 * inch),
        Paragraph("<b>Statement Date:</b> October 15, 2025", s["Normal"]),
        Paragraph("<b>Reporting Period End (As of Date):</b> September 30, 2025", s["Normal"]),
        Spacer(1, 0.1 * inch),
        Paragraph(
            "The figures below report Limited Partner Y's own capital account "
            "position. All amounts are the Limited Partner's, not the Fund's.",
            s["Normal"]),
        Spacer(1, 0.25 * inch),
    ]
    data = [["Line Item", "Q1 2025", "Q2 2025", "Q3 2025"]] + ROWS_ALL
    el.append(_table(data, [2.4 * inch, 1.35 * inch, 1.35 * inch, 1.35 * inch]))
    el.append(Spacer(1, 0.25 * inch))
    el.append(Paragraph(
        "All figures are presented on an inception-to-date basis as of the "
        "reporting period end date shown above. Prior period columns are "
        "provided for comparative purposes only.", s["Normal"]))
    doc.build(el)
    print(f"Wrote {out.name}")


if __name__ == "__main__":
    build_variant_a()
    build_variant_b()
