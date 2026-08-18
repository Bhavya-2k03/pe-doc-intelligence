"""
Generate the demo Capital Account Statement PDFs that replace the body-only
capital-account emails (e037/e038/e039) in the three demo scenarios.

Design constraints (deliberate):
  - The FINAL column reproduces the exact (value, as-of date) the current
    email bodies carry today — so scenario outcomes are unchanged; earlier
    columns only add correctly-dated history to the timeline.
  - Layout matches the battle-tested shape (fund letterhead + LP subject +
    period columns): measured ~100% extraction at reasoning effort "low"
    (scripts/battle_test_extraction.py).
  - mfn_flow gets the CHART variant (labeled bars — values printed on bars,
    so parsed cells carry full dollar amounts, avoiding the unit-in-header
    normalization trap observed with unlabeled charts).

Outputs to backend/local_packages/files/ (gitignored; local testing only —
push to Supabase later via push_packages.py once validated).

Run from backend/: python scripts/generate_demo_capital_statements.py
"""
from pathlib import Path

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

OUT_DIR = Path(__file__).resolve().parent.parent / "local_packages" / "files"

FOOTNOTE = (
    "All figures are presented on an inception-to-date basis. Prior period "
    "columns are provided for comparative purposes only."
)


def _styled_table(data, col_widths):
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


def _header_elements(styles, statement_date: str):
    return [
        Paragraph("10x Growth Fund, L.P.", styles["Title"]),
        Paragraph("Limited Partner Capital Account Statement", styles["Heading2"]),
        Spacer(1, 0.12 * inch),
        Paragraph("<b>Limited Partner:</b> Limited Partner Y", styles["Normal"]),
        Paragraph(f"<b>Statement Date:</b> {statement_date}", styles["Normal"]),
        Spacer(1, 0.25 * inch),
    ]


def build_table_statement(filename: str, statement_date: str,
                          columns: list[str], rows: list[list[str]]):
    out = OUT_DIR / filename
    doc = SimpleDocTemplate(str(out), pagesize=letter,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch)
    s = getSampleStyleSheet()
    el = _header_elements(s, statement_date)
    data = [["Line Item"] + columns] + rows
    n = len(columns)
    el.append(_styled_table(data, [2.3 * inch] + [(4.3 / n) * inch] * n))
    el.append(Spacer(1, 0.25 * inch))
    el.append(Paragraph(FOOTNOTE, s["Normal"]))
    doc.build(el)
    print(f"Wrote {out}")


def build_chart_statement(filename: str, statement_date: str,
                          categories: list[str], values: list[int],
                          commitment_note: str):
    out = OUT_DIR / filename
    doc = SimpleDocTemplate(str(out), pagesize=letter,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch)
    s = getSampleStyleSheet()
    el = _header_elements(s, statement_date)

    d = Drawing(440, 250)
    chart = VerticalBarChart()
    chart.x, chart.y = 50, 40
    chart.width, chart.height = 360, 160
    chart.data = [values]
    chart.categoryAxis.categoryNames = categories
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 10_000_000
    chart.valueAxis.valueStep = 2_000_000
    chart.valueAxis.labelTextFormat = lambda v: f"${v/1e6:.0f}M"
    chart.bars[0].fillColor = colors.HexColor("#1f6f8b")
    # Data labels ON the bars: parsed cells then carry full dollar values.
    chart.barLabelFormat = lambda v: f"${v:,.0f}"
    chart.barLabels.nudge = 10
    chart.barLabels.fontSize = 8
    d.add(chart)
    d.add(String(50, 230, "Investor Invested Capital",
                 fontSize=12, fontName="Helvetica-Bold"))
    el.append(d)

    el.append(Spacer(1, 0.25 * inch))
    el.append(Paragraph(
        f"The chart above presents the Limited Partner's invested capital at "
        f"each period end. {commitment_note}", s["Normal"]))
    doc.build(el)
    print(f"Wrote {out}")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Row selection is deliberate: every row maps to a registry field with an
    # engine consumer (commitment/invested -> fee bases; distributions ->
    # INVESTOR_REALIZATION_PCT). "Cumulative Capital Called" (no V1 consumer)
    # and "Unfunded Commitment" (derived: commitment - invested; derived
    # quantities are computed at evaluation time, never stored as their own
    # timeline) are intentionally absent.

    # Reporting periods are spaced two fiscal quarters apart so consecutive
    # observations do not collide on the timeline, and EVERY reported period
    # closed before the statement date — a statement cannot report a period
    # that has not ended yet. Fund fiscal quarters are anchored to the
    # 2024-01-15 initial closing, so they end Jan 14 / Apr 14 / Jul 14 / Oct 14.
    #
    # e038 statement date 2028-12-01 → latest closed quarter is Q3 2028 (ended
    #   2028-10-14). Q4 2028 does not close until 2029-01-14 and is excluded.
    # e039 statement date 2030-06-15 → latest closed quarter is Q1 2030 (ended
    #   2030-04-14). Q2 2030 does not close until 2030-07-14 and is excluded.
    #
    # The final column keeps the value the email body used to state, so
    # scenario outcomes are unchanged; earlier columns add dated history.

    # side_letter_flow (e038): final value $8.2M, previously "as of Dec 1, 2028"
    build_table_statement(
        "LP_CAPITAL_ACCOUNT_STATEMENT_DEC2028.pdf",
        statement_date="December 1, 2028",
        columns=["Q3 2027", "Q1 2028", "Q3 2028"],
        rows=[
            ["Capital Commitment", "$10,000,000", "$10,000,000", "$10,000,000"],
            ["Invested Capital (cost basis)", "$7,400,000", "$7,800,000", "$8,200,000"],
            ["Cumulative Distributions", "$1,250,000", "$1,400,000", "$1,600,000"],
        ],
    )

    # multi_amendment (e039): final value $8.5M, previously "as of Jun 15, 2030"
    build_table_statement(
        "LP_CAPITAL_ACCOUNT_STATEMENT_JUN2030.pdf",
        statement_date="June 15, 2030",
        columns=["Q1 2029", "Q3 2029", "Q1 2030"],
        rows=[
            ["Capital Commitment", "$10,000,000", "$10,000,000", "$10,000,000"],
            ["Invested Capital (cost basis)", "$8,100,000", "$8,300,000", "$8,500,000"],
            ["Cumulative Distributions", "$1,900,000", "$2,050,000", "$2,200,000"],
        ],
    )

    # mfn_flow (e037): CHART variant — same end state as e038. Bars are also
    # two quarters apart and all periods closed before the statement date.
    build_chart_statement(
        "LP_CAPITAL_ACCOUNT_CHART_DEC2028.pdf",
        statement_date="December 1, 2028",
        categories=["Q1 2027", "Q3 2027", "Q1 2028", "Q3 2028"],
        values=[7_000_000, 7_400_000, 7_800_000, 8_200_000],
        commitment_note="Total capital commitment: $10,000,000.",
    )


if __name__ == "__main__":
    main()
