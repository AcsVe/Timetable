"""PDF export with ReportLab (pure Python — no system libraries needed on Render).

Arabic is shaped (arabic-reshaper) and put in visual order (python-bidi); Arabic glyphs are
drawn with Noto Naskh Arabic and Latin/digits with DejaVu Sans, switched per run of text.
For Arabic reports every table is mirrored so the first column is on the right."""
from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.reports.data import Grid, Report
from app.reports.data import Table as DataTable

FONT_DIR = Path(__file__).resolve().parent / "fonts"
_registered = False
ACCENT = colors.HexColor("#1F4E8C")
LIGHT = colors.HexColor("#E8EEF7")
MISSING = colors.HexColor("#EEEEEE")
LINE = colors.HexColor("#B8C2D0")


def _register():
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont("Naskh", str(FONT_DIR / "NotoNaskhArabic-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Naskh-Bold", str(FONT_DIR / "NotoNaskhArabic-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    _registered = True


_reshaper = arabic_reshaper.ArabicReshaper(configuration={"delete_harakat": False, "support_ligatures": True})


def _is_arabic(ch: str) -> bool:
    o = ord(ch)
    return 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF


def _width(text: str, size: float, bold: bool) -> float:
    ar, lat = ("Naskh-Bold", "DejaVu-Bold") if bold else ("Naskh", "DejaVu")
    shaped = _reshaper.reshape(text)
    return sum(pdfmetrics.stringWidth(ch, ar if _is_arabic(ch) else lat, size) for ch in shaped)


def _wrap_logical(line: str, width: float | None, size: float, bold: bool) -> list[str]:
    """Wrap in *logical* order before bidi, so RTL lines break in the right place and order."""
    if not width or _width(line, size, bold) <= width:
        return [line]
    out, cur = [], ""
    for word in line.split(" "):
        cand = f"{cur} {word}".strip()
        if cur and _width(cand, size, bold) > width:
            out.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        out.append(cur)
    return out


def rich(text, rtl: bool, bold: bool = False, width: float | None = None, size: float = 8.5) -> str:
    """Paragraph markup: wrapped, shaped, visually ordered, with a font switch per script run.
    Lines containing no Arabic letters (times, numbers, Latin names) are laid out left-to-right."""
    ar_font, lat_font = ("Naskh-Bold", "DejaVu-Bold") if bold else ("Naskh", "DejaVu")
    lines = []
    logical = []
    for line in str("" if text is None else text).split("\n"):
        logical += _wrap_logical(line, width, size, bold)
    for line in logical:
        has_ar = any(_is_arabic(ch) for ch in line)
        visual = get_display(_reshaper.reshape(line), base_dir="R" if (rtl and has_ar) else "L")
        runs, cur, cur_font = [], "", None
        for ch in visual:
            f = ar_font if _is_arabic(ch) else (cur_font if ch == " " and cur_font else lat_font)
            if f != cur_font and cur:
                runs.append((cur_font, cur))
                cur = ""
            cur_font = f
            cur += ch
        if cur:
            runs.append((cur_font, cur))
        lines.append("".join(f'<font name="{f}">{escape(s)}</font>' for f, s in runs))
    return "<br/>".join(lines)


def _styles(rtl: bool):
    align = TA_RIGHT if rtl else TA_LEFT
    return {
        "cell": ParagraphStyle("cell", fontName="DejaVu", fontSize=8, leading=11, alignment=TA_CENTER),
        "text": ParagraphStyle("text", fontName="DejaVu", fontSize=8.5, leading=12, alignment=align),
        "num": ParagraphStyle("num", fontName="DejaVu", fontSize=8.5, leading=12, alignment=TA_CENTER),
        "head": ParagraphStyle("head", fontName="DejaVu-Bold", fontSize=8.5, leading=12, alignment=TA_CENTER,
                               textColor=colors.white),
        "sub": ParagraphStyle("sub", fontName="DejaVu", fontSize=11, leading=15, alignment=TA_CENTER,
                              textColor=ACCENT),
        "foot": ParagraphStyle("foot", fontName="DejaVu", fontSize=8, leading=11, alignment=align,
                               textColor=colors.HexColor("#555555")),
    }


def _fmt(v, percent=False):
    if v is None:
        return ""
    if percent and isinstance(v, (int, float)):
        return f"{round(v * 100)}%"
    return str(v)


def _grid_flowables(rep: Report, g: Grid, st, width) -> list:
    rtl = rep.rtl
    n = len(g.days)
    first_w = 2.6 * cm
    day_w = (width - first_w) / max(n, 1)
    cw = day_w - 8
    head = [Paragraph(rich("الحصة" if rtl else "Period", rtl, True), st["head"])] + \
           [Paragraph(rich(d, rtl, True, cw), st["head"]) for d in g.days]
    data, missing_cells = [head], []
    for i, (p, tl) in enumerate(g.periods, start=1):
        row = [Paragraph(rich(f"{p}\n{tl}" if tl else str(p), rtl, True), st["cell"])]
        for d in range(len(g.days)):
            if (d, p) in g.missing:
                row.append("")
                missing_cells.append((d + 1, i))
                continue
            entries = g.cells.get((d, p), [])
            text = "\n".join("\n".join(x for x in e if x) for e in entries)
            row.append(Paragraph(rich(text, rtl, width=cw, size=8), st["cell"]) if text else "")
        data.append(row)
    col_w = [first_w] + [day_w] * n
    if rtl:
        data = [list(reversed(r)) for r in data]
        col_w = list(reversed(col_w))
        missing_cells = [(n - c, r) for c, r in missing_cells]
    t = Table(data, colWidths=col_w, repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    period_col = n if rtl else 0
    style.append(("BACKGROUND", (period_col, 1), (period_col, -1), LIGHT))
    for c, r in missing_cells:
        style.append(("BACKGROUND", (c, r), (c, r), MISSING))
    t.setStyle(TableStyle(style))
    out = [Paragraph(rich(g.title, rtl, True), st["sub"]), Spacer(1, 6), t]
    if g.footer:
        out += [Spacer(1, 6), Paragraph(rich(g.footer, rtl), st["foot"])]
    return out


def _table_flowables(rep: Report, tb: DataTable, st, width) -> list:
    rtl = rep.rtl
    ncol = len(tb.columns)
    # Wider columns for text, narrow for numbers.
    weights = [1.0 if (j in tb.numeric or j in tb.percent) else 2.6 for j in range(ncol)]
    col_w = [width * w / sum(weights) for w in weights]
    data = [[Paragraph(rich(c, rtl, True, col_w[j] - 8), st["head"]) for j, c in enumerate(tb.columns)]]
    rows = list(tb.rows) + ([tb.totals] if tb.totals else [])
    for i, r in enumerate(rows):
        bold = tb.totals is not None and i == len(rows) - 1
        cells = []
        for j, v in enumerate(r):
            numeric = j in tb.numeric or j in tb.percent
            cells.append(Paragraph(rich(_fmt(v, j in tb.percent), rtl, bold or j == 0, col_w[j] - 8),
                                   st["num" if numeric else "text"]))
        data.append(cells)
    if rtl:
        data = [list(reversed(r)) for r in data]
        col_w = list(reversed(col_w))
    t = Table(data, colWidths=col_w, repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FC")]),
    ]
    if tb.totals:
        style.append(("BACKGROUND", (0, -1), (-1, -1), LIGHT))
    t.setStyle(TableStyle(style))
    return [Paragraph(rich(tb.title, rtl, True), st["sub"]), Spacer(1, 6), t]


def render_pdf(rep: Report, logo: bytes | None) -> bytes:
    _register()
    rtl = rep.rtl
    wide = bool(rep.grids) or any(len(t.columns) > 5 for t in rep.tables)
    pagesize = landscape(A4) if wide else A4
    st = _styles(rtl)
    buf = io.BytesIO()
    top = 3.3 * cm
    doc = SimpleDocTemplate(buf, pagesize=pagesize, leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=top, bottomMargin=1.4 * cm, title=rep.title, author=rep.school_name)
    width = pagesize[0] - doc.leftMargin - doc.rightMargin
    logo_img = None
    if logo:
        try:
            logo_img = ImageReader(io.BytesIO(logo))
        except Exception:
            logo_img = None

    def header(canvas, _doc):
        canvas.saveState()
        pw, ph = pagesize
        y = ph - 1.1 * cm
        if logo_img:
            iw, ih = logo_img.getSize()
            h = 1.9 * cm
            w = iw * h / ih
            x = pw - doc.rightMargin - w if rtl else doc.leftMargin
            canvas.drawImage(logo_img, x, ph - 0.7 * cm - h, width=w, height=h, mask="auto", preserveAspectRatio=True)
        for text, size, bold, color in ((rep.school_name, 14, True, ACCENT), (rep.title, 12, True, colors.black),
                                        (" — ".join(x for x in (rep.timetable_name, rep.filters) if x), 9, False,
                                         colors.HexColor("#444444"))):
            p = Paragraph(rich(text, rtl, bold, pw - 2 * doc.leftMargin - 5.5 * cm, size), ParagraphStyle("h", fontName="DejaVu", fontSize=size, leading=size + 3,
                                                                alignment=TA_CENTER, textColor=color))
            _w, hgt = p.wrap(pw - 2 * doc.leftMargin - 5 * cm, 3 * cm)
            p.drawOn(canvas, doc.leftMargin + 2.5 * cm, y - hgt + size)
            y -= hgt + 1
        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(1.2)
        canvas.line(doc.leftMargin, ph - top + 0.35 * cm, pw - doc.rightMargin, ph - top + 0.35 * cm)
        footer = f"{rep.generated_at}   ·   {'صفحة' if rtl else 'Page'} {canvas.getPageNumber()}"
        fp = Paragraph(rich(footer, rtl), st["foot"])
        fp.wrap(pw - doc.leftMargin - doc.rightMargin, 1 * cm)
        fp.drawOn(canvas, doc.leftMargin, 0.7 * cm)
        canvas.restoreState()

    story = []
    for i, g in enumerate(rep.grids):
        if i:
            story.append(PageBreak())
        story += _grid_flowables(rep, g, st, width)
    for t in rep.tables:
        story += _table_flowables(rep, t, st, width)
    if not story:
        story.append(Paragraph(rich("لا توجد بيانات مطابقة" if rtl else "No matching data", rtl), st["sub"]))
    doc.build(story, onFirstPage=header, onLaterPages=header)
    return buf.getvalue()
