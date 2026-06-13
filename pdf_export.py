"""Builds a clean one-page-plus PDF of a FestivalScout strategy, in code.

Takes the analysis payload the frontend already has and renders it with
reportlab, so the download is a real PDF (no browser print dialog).
"""
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

INK = colors.HexColor("#14110f")
AMBER = colors.HexColor("#c07f1d")
MUTED = colors.HexColor("#6f6354")
OK = colors.HexColor("#5d7a4a")
WARN = colors.HexColor("#b07a1f")
BAD = colors.HexColor("#a83a31")

VERDICT_COLOR = {
    "fit": OK, "caution": WARN, "not_eligible": BAD,
    "closed": BAD, "unknown": MUTED,
}
VERDICT_LABEL = {
    "fit": "Fit", "caution": "Caution", "not_eligible": "Not eligible",
    "closed": "Window closed", "unknown": "Verify dates",
}


def build_strategy_pdf(data: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.8 * inch, rightMargin=0.8 * inch,
        topMargin=0.8 * inch, bottomMargin=0.8 * inch,
        title="FestivalScout Strategy",
    )
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=INK, fontSize=22, spaceAfter=2)
    eyebrow = ParagraphStyle("eyebrow", parent=ss["Normal"], textColor=AMBER, fontSize=8,
                             spaceAfter=10, leading=10)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=AMBER, fontSize=11, spaceBefore=14)
    body = ParagraphStyle("body", parent=ss["Normal"], textColor=INK, fontSize=10, leading=14)
    small = ParagraphStyle("small", parent=ss["Normal"], textColor=MUTED, fontSize=8, leading=11)

    film = data["film"]
    genres = film.get("genres") or ([film["genre"]] if film.get("genre") else [])
    story = []
    story.append(Paragraph("FESTIVALSCOUT &middot; SUBMISSION STRATEGY", eyebrow))
    story.append(Paragraph(film["title"], h1))
    story.append(Paragraph(
        f'{film["runtime_minutes"]} min &middot; {", ".join(genres)} &middot; '
        f'completed {film["completion_date"]} &middot; premiere status: {film["premiere_status"]}',
        small,
    ))

    notes = data.get("strategy_notes") or []
    if notes:
        story.append(Paragraph("Strategy", h2))
        for n in notes:
            story.append(Paragraph("&bull; " + n, body))
    if data.get("total_estimated_fees_usd") is not None:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f'Estimated total fees for open fits: about ${data["total_estimated_fees_usd"]} USD', body))

    story.append(Paragraph("Festival verdicts", h2))
    cell = ParagraphStyle("cell", parent=ss["Normal"], textColor=INK, fontSize=8.5, leading=10.5)
    cell_b = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")
    head_st = ParagraphStyle("head", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")

    def vcell(text, color):
        return Paragraph(text, ParagraphStyle("v", parent=cell_b, textColor=color))

    rows = [[
        Paragraph("Festival", head_st), Paragraph("Verdict", head_st),
        Paragraph("Format", head_st), Paragraph("Next deadline", head_st),
        Paragraph("Fee", head_st),
    ]]
    for v in data["verdicts"]:
        nd = v.get("next_deadline")
        if nd:
            deadline = f'{nd["date"]} ({nd["days_remaining"]}d)'
            fee = f'{nd["fee"]} {nd["currency"]}' if nd.get("fee") is not None else "see source"
        else:
            deadline, fee = "\u2014", "\u2014"
        rows.append([
            Paragraph(v["festival_name"], cell),
            vcell(VERDICT_LABEL.get(v["verdict"], v["verdict"]), VERDICT_COLOR.get(v["verdict"], MUTED)),
            Paragraph(v["film_format"], cell),
            Paragraph(deadline, cell),
            Paragraph(fee, cell),
        ])
    table = Table(rows, colWidths=[2.55 * inch, 0.95 * inch, 0.7 * inch, 1.25 * inch, 0.95 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5efe2")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#d8cfbd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(table)

    if data.get("agent_analysis"):
        story.append(Paragraph("Agent analysis (Foundry IQ)", h2))
        for para in data["agent_analysis"].split("\n"):
            if para.strip():
                story.append(Paragraph(para.strip().replace("<", "&lt;").replace(">", "&gt;"), body))

    story.append(Spacer(1, 16))
    story.append(Paragraph(
        f"Generated by FestivalScout on {date.today().isoformat()}. "
        "Festival data is verified periodically against official sources but changes yearly; "
        "always confirm deadlines and fees on each festival's own page before submitting.",
        small,
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()
