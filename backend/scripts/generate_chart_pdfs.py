"""
Chart extraction feasibility test — generates two bar-chart PDFs:

  _chart_labeled.pdf   — quarterly invested capital bar chart WITH data
                         labels printed above each bar (OCR-recoverable)
  _chart_unlabeled.pdf — same chart, NO data labels (values only inferable
                         from bar heights vs axis — not OCR-recoverable)

Parsed by scripts/observe_chart_parsing.py under different LlamaParse
configs to answer: can we honestly demo chart extraction?

Run from backend/: python scripts/generate_chart_pdfs.py
"""
from pathlib import Path

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.textlabels import Label
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

HERE = Path(__file__).resolve().parent

QUARTERS = ["Q4 2027", "Q1 2028", "Q2 2028", "Q3 2028"]
VALUES = [6_400_000, 7_100_000, 7_800_000, 8_200_000]


def make_chart(labeled: bool) -> Drawing:
    d = Drawing(440, 240)
    chart = VerticalBarChart()
    chart.x = 50
    chart.y = 40
    chart.width = 360
    chart.height = 160
    chart.data = [VALUES]
    chart.categoryAxis.categoryNames = QUARTERS
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 10_000_000
    chart.valueAxis.valueStep = 2_000_000
    chart.valueAxis.labelTextFormat = lambda v: f"${v/1e6:.0f}M"
    chart.bars[0].fillColor = colors.HexColor("#1f6f8b")
    if labeled:
        chart.barLabelFormat = lambda v: f"${v:,.0f}"
        chart.barLabels.nudge = 10
        chart.barLabels.fontSize = 8
    d.add(chart)
    d.add(String(50, 220, "Investor Invested Capital by Quarter",
                 fontSize=12, fontName="Helvetica-Bold"))
    return d


def build(labeled: bool):
    suffix = "labeled" if labeled else "unlabeled"
    out = HERE / f"_chart_{suffix}.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=letter,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch)
    s = getSampleStyleSheet()
    el = [
        Paragraph("10x Growth Fund, L.P.", s["Title"]),
        Paragraph("Limited Partner Capital Account — Quarterly Summary", s["Heading2"]),
        Spacer(1, 0.1 * inch),
        Paragraph("<b>Limited Partner:</b> Limited Partner Y", s["Normal"]),
        Paragraph("<b>Statement Date:</b> December 1, 2028", s["Normal"]),
        Spacer(1, 0.3 * inch),
        make_chart(labeled),
        Spacer(1, 0.3 * inch),
        Paragraph(
            "The chart above presents the Limited Partner's invested capital "
            "at each quarter end. Total capital commitment: $10,000,000.",
            s["Normal"]),
    ]
    doc.build(el)
    print(f"Wrote {out.name}")


if __name__ == "__main__":
    build(labeled=True)
    build(labeled=False)
