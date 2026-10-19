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

from app.reports.data import Grid, Report, TimeLine, grid_matrix
from app.reports.data import Table as DataTable

FONT_DIR = Path(__file__).resolve().parent / "fonts"
_registered = False
ACCENT = colors.HexColor("#1F4E8C")
LIGHT = colors.HexColor("#E8EEF7")
MISSING = colors.HexColor("#EEEEEE")
LINE = colors.HexColor("#B8C2D0")


class Palette:
    """'plain' prints clean black tables on white — no shading anywhere (black-and-white printers);
    'color' keeps the blue header band and light row shading."""

    def __init__(self, style: str):
        self.plain = style != "color"
        self.accent = colors.black if self.plain else ACCENT
        self.head_bg = None if self.plain else ACCENT
        self.head_fg = colors.black if self.plain else colors.white
        self.label_bg = None if self.plain else LIGHT
        self.missing_bg = None if self.plain else MISSING
        self.line = colors.black if self.plain else LINE
        self.line_w = 0.6 if self.plain else 0.5
        self.zebra = None if self.plain else [colors.white, colors.HexColor("#F7F9FC")]
        self.total_bg = None if self.plain else LIGHT
        self.muted = "#000000" if self.plain else "#555555"


def _register():
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont("Naskh", str(FONT_DIR / "NotoNaskhArabic-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Naskh-Bold", str(FONT_DIR / "NotoNaskhArabic-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    _registered = True


_TIME_RANGE = __import__("re").compile(r"(\d{1,2}:\d{2})\u200e?\s*([–-])\s*\u200e?(\d{1,2}:\d{2})")
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
        # Arabic letters decide the direction; Arabic punctuation alone («،» between Latin names) does not
        has_ar = any(_is_arabic(ch) and ch not in "،؛؟" for ch in line)
        line = _TIME_RANGE.sub("\\1\u200e\\2\u200e\\3", line)   # «08:00–08:45» stays in reading order inside Arabic
        visual = get_display(_reshaper.reshape(line), base_dir="R" if (rtl and has_ar) else "L").replace("\u200e", "")
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


def _styles(rtl: bool, pal: "Palette | None" = None):
    align = TA_RIGHT if rtl else TA_LEFT
    pal = pal or Palette("color")
    return {
        "cell": ParagraphStyle("cell", fontName="DejaVu", fontSize=8, leading=11, alignment=TA_CENTER),
        "text": ParagraphStyle("text", fontName="DejaVu", fontSize=8.5, leading=12, alignment=align),
        "num": ParagraphStyle("num", fontName="DejaVu", fontSize=8.5, leading=12, alignment=TA_CENTER),
        "head": ParagraphStyle("head", fontName="DejaVu-Bold", fontSize=8.5, leading=12, alignment=TA_CENTER,
                               textColor=pal.head_fg),
        "sub": ParagraphStyle("sub", fontName="DejaVu", fontSize=11, leading=15, alignment=TA_CENTER,
                              textColor=pal.accent),
        "foot": ParagraphStyle("foot", fontName="DejaVu", fontSize=8, leading=11, alignment=align,
                               textColor=colors.HexColor(pal.muted)),
        "tiny": ParagraphStyle("tiny", fontName="DejaVu", fontSize=6.2, leading=7.6, alignment=TA_CENTER),
        "tinyhead": ParagraphStyle("tinyhead", fontName="DejaVu-Bold", fontSize=6.5, leading=8, alignment=TA_CENTER,
                                   textColor=pal.head_fg),
    }


def _fmt(v, percent=False):
    if v is None:
        return ""
    if percent and isinstance(v, (int, float)):
        return f"{round(v * 100)}%"
    return str(v)


# Largest text size per print size; the timetable then takes the largest size up to it at which every word
# fits its column and every row fits its share of the page.
GRID_FONT = {"normal": 10.0, "large": 13.0, "xlarge": 16.0}


def _small(size: float) -> float:
    return max(size - 1.8, 5.5)


def _cell_height(entries, width: float, size: float) -> float | None:
    """Height of a cell's text at this size, or None when a single word is wider than the column."""
    total = 0.0
    for e in entries or []:
        lines = [x for x in e if x]
        for i, x in enumerate(lines):
            first = i == 0 and not isinstance(x, TimeLine)
            s = size if first else _small(size)
            for part in str(x).split("\n"):
                if any(_width(w, s, first) > width for w in part.split(" ") if w):
                    return None
                total += len(_wrap_logical(part, width, s, first)) * (s + 3)
    return total


def _fit_size(heads, rows, cw: float, first_w: float, top: float, even: float | None) -> float:
    size = top
    while size > 6:
        ok = all(_cell_height([[x]], cw, size + 0.5) is not None for x in heads)
        for label, cells, _m in rows:
            if not ok:
                break
            if _cell_height([[label]], first_w - 6, size + 0.5) is None:
                ok = False
                break
            for x in cells:
                hgt = _cell_height(x, cw, size)
                if hgt is None or (even and hgt + 8 > even):
                    ok = False
                    break
        if ok:
            return size
        size -= 0.5
    return 6


def _grid_flowables(rep: Report, g: Grid, st, width, pal: Palette, avail_h: float | None = None) -> list:
    """One timetable on its page. The rows share the page height (avail_h), so the table fills the sheet
    and stays readable when handed out; rep.size makes the text larger still."""
    rtl = rep.rtl
    corner, heads, rows = grid_matrix(g, rep.layout, rtl, raw=True)
    n = len(heads)
    top_size = GRID_FONT.get(rep.size, GRID_FONT["normal"])
    # the label column (days or period times) only as wide as its text needs, the rest goes to the lessons
    label_w = max([_width(part, top_size + 0.5, True) for lb, _c, _m in rows for part in str(lb).split("\n")] + [0])
    first_w = min(max(label_w + 16, 2.0 * cm), 3.6 * cm)
    col = (width - first_w) / max(n, 1)
    cw = col - 14          # the cell's padding (6 + 6) and a little room
    head_guess = 2 * (top_size + 4.5) + 8
    even_guess = (avail_h - head_guess) / max(len(rows), 1) if avail_h else None
    size = _fit_size(heads, rows, cw, first_w, top_size, even_guess)
    head_st = ParagraphStyle("gh", parent=st["head"], fontSize=size + 0.5, leading=size + 4)
    label_st = ParagraphStyle("gl", parent=st["cell"], fontSize=size + 0.5, leading=size + 4)
    data = [[Paragraph(rich(corner, rtl, True, None, size + 0.5), head_st)] +
            [Paragraph(rich(x, rtl, True, cw, size + 0.5), head_st) for x in heads]]
    missing_cells = []
    for i, (label, cells, missing) in enumerate(rows, start=1):
        row = [Paragraph(rich(label, rtl, True, first_w - 6, size + 0.5), label_st)]
        for j, (entries, miss) in enumerate(zip(cells, missing)):
            if miss:
                missing_cells.append((j + 1, i))
            if miss and pal.plain:
                row.append(Paragraph(rich("—", rtl), st["cell"]))
                continue
            row.append(Paragraph(_cell_markup(entries, rtl, cw, size, pal.muted),
                                 ParagraphStyle("c", parent=st["cell"], fontSize=size, leading=size + 3))
                       if entries and not miss else "")
        data.append(row)
    col_w = [first_w] + [col] * n
    if rtl:
        data = [list(reversed(r)) for r in data]
        col_w = list(reversed(col_w))
        missing_cells = [(n - c, r) for c, r in missing_cells]
    # The rows share the page height evenly (ASC print style), never less than their text needs.
    head_lines = max([1] + [str(x).count("\n") + 1 for x in heads])
    head_h = head_lines * (size + 4.5) + 8
    if avail_h:
        even = max(1.2 * cm, (avail_h - head_h) / max(len(rows), 1))
    else:
        even = max(1.6 * cm, min(3.2 * cm, 11 * cm / max(len(rows), 1))) if rep.layout == "rows" else 0
    row_h = [head_h]
    for _label, cells, _m in rows:
        need = max([size + 3] + [(_cell_height(x, cw, size) or 0) for x in cells]) + 8
        row_h.append(max(even, need))
    t = Table(data, colWidths=col_w, rowHeights=row_h, repeatRows=1)
    label_col = n if rtl else 0
    style = [
        ("GRID", (0, 0), (-1, -1), pal.line_w, pal.line),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if pal.plain:   # emphasis by line weight instead of shading
        style += [("LINEBELOW", (0, 0), (-1, 0), 1.4, colors.black), ("BOX", (0, 0), (-1, -1), 1.4, colors.black),
                  ("LINEAFTER" if not rtl else "LINEBEFORE", (label_col, 0), (label_col, -1), 1.4, colors.black)]
    else:
        style += [("BACKGROUND", (0, 0), (-1, 0), pal.head_bg),
                  ("BACKGROUND", (label_col, 1), (label_col, -1), pal.label_bg)]
        for c, r in missing_cells:
            style.append(("BACKGROUND", (c, r), (c, r), pal.missing_bg))
    t.setStyle(TableStyle(style))
    out = [Paragraph(rich(g.title, rtl, True), st["sub"])]
    if g.subtitle:
        out.append(Paragraph(rich(g.subtitle, rtl), st["cell"]))
    out += [Spacer(1, 6), t]
    if g.footer:
        out += [Spacer(1, 6), Paragraph(rich(g.footer, rtl), st["foot"])]
    return out


def _cell_markup(entries: list[list[str]], rtl: bool, width: float, size: float, muted: str = "#555555") -> str:
    """One timetable cell: the subject in bold, the teacher (and room) below it in a smaller grey font."""
    small = _small(size)
    parts = []
    for e in entries:
        lines = [x for x in e if x]
        if not lines:
            continue
        if isinstance(lines[0], TimeLine):     # the period's own time on a day with different times
            parts.append(f'<font size="{small}" color="{muted}">{rich(lines[0], rtl, False, width, small)}</font>')
            continue
        parts.append(rich(lines[0], rtl, True, width, size))
        for x in lines[1:]:
            parts.append(f'<font size="{small}" color="{muted}">{rich(x, rtl, False, width, small)}</font>')
    return "<br/>".join(parts)


def _table_flowables(rep: Report, tb: DataTable, st, width, pal: Palette) -> list:
    rtl = rep.rtl
    ncol = len(tb.columns)
    if tb.compact:   # master timetables: a narrow label column and many equal columns
        first = min(3.2 * cm, width * 0.16)
        col_w = [first] + [(width - first) / max(ncol - 1, 1)] * (ncol - 1)
        head_st, cell_st = st["tinyhead"], st["tiny"]
        size = 6.2
    else:
        # Wider columns for text, narrow for numbers.
        weights = [1.0 if (j in tb.numeric or j in tb.percent) else 2.6 for j in range(ncol)]
        col_w = [width * w / sum(weights) for w in weights]
        head_st, cell_st = st["head"], None
        size = 8.5
    data = []
    group_row = None
    if tb.group_header:
        group_row = []
        spans = []
        col = 0
        for label, span in tb.group_header:
            # the visible cell of a span is its first one on the page: the right-most in Arabic (rows are mirrored)
            cell = Paragraph(rich(label, rtl, True), head_st)
            group_row += ([""] * (span - 1) + [cell]) if rtl else ([cell] + [""] * (span - 1))
            if span > 1:
                spans.append((col, col + span - 1))
            col += span
        data.append(group_row)
    data.append([Paragraph(rich(c, rtl, True, col_w[j] - 6, size), head_st) for j, c in enumerate(tb.columns)])
    head_rows = len(data)
    rows = list(tb.rows) + ([tb.totals] if tb.totals else [])
    for i, r in enumerate(rows):
        bold = tb.totals is not None and i == len(rows) - 1
        cells = []
        for j, v in enumerate(r):
            numeric = j in tb.numeric or j in tb.percent
            style_ = cell_st or st["num" if numeric else "text"]
            cells.append(Paragraph(rich(_fmt(v, j in tb.percent), rtl, bold or j == 0, col_w[j] - 6, size), style_))
        data.append(cells)
    if rtl:
        data = [list(reversed(r)) for r in data]
        col_w = list(reversed(col_w))
    t = Table(data, colWidths=col_w, repeatRows=head_rows)
    flip = (lambda c: ncol - 1 - c) if rtl else (lambda c: c)  # noqa: E731
    style = [
        ("GRID", (0, 0), (-1, -1), pal.line_w, pal.line),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if tb.compact:
        style += [("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                  ("LEFTPADDING", (0, 0), (-1, -1), 1.5), ("RIGHTPADDING", (0, 0), (-1, -1), 1.5)]
    if tb.group_header:
        for a, b in spans:
            a2, b2 = sorted((flip(a), flip(b)))
            style.append(("SPAN", (a2, 0), (b2, 0)))
            style.append(("LINEBEFORE" if not rtl else "LINEAFTER", (flip(a), 0), (flip(a), -1), 1.3, pal.accent))
    for r in tb.row_groups:
        if r > 0:
            style.append(("LINEABOVE", (0, r + head_rows), (-1, r + head_rows), 1.3, pal.accent))
    if pal.plain:
        style += [("LINEBELOW", (0, head_rows - 1), (-1, head_rows - 1), 1.4, colors.black),
                  ("BOX", (0, 0), (-1, -1), 1.4, colors.black)]
        if tb.totals:
            style.append(("LINEABOVE", (0, -1), (-1, -1), 1.4, colors.black))
    else:
        style += [("BACKGROUND", (0, 0), (-1, head_rows - 1), pal.head_bg),
                  ("ROWBACKGROUNDS", (0, head_rows), (-1, -1), pal.zebra)]
        if tb.totals:
            style.append(("BACKGROUND", (0, -1), (-1, -1), pal.total_bg))
        for (r, c), color in tb.cell_colors.items():
            cc = flip(c)
            style.append(("BACKGROUND", (cc, r + head_rows), (cc, r + head_rows), _tint(color)))
    t.setStyle(TableStyle(style))
    out = [Paragraph(rich(tb.title, rtl, True), st["sub"])] if tb.title and tb.title != rep.title else []
    if tb.subtitle:
        out.append(Paragraph(rich(tb.subtitle, rtl), st["cell"]))
    out += [Spacer(1, 6), t]
    if tb.rows and not tb.compact:
        out += [Spacer(1, 3), Paragraph(rich(f"{'عدد الصفوف' if rtl else 'Rows'}: {len(tb.rows)}", rtl), st["foot"])]
    return out


def _tint(hex_color: str, amount: float = 0.25):
    c = colors.HexColor(hex_color)
    return colors.Color(1 - (1 - c.red) * amount, 1 - (1 - c.green) * amount, 1 - (1 - c.blue) * amount)


def _signature_flowable(rep: Report, st, width):
    if not rep.signature:
        return []
    rtl = rep.rtl
    cells = [Paragraph(rich(f"{x}\n\n" + "." * 28, rtl, True), st["cell"]) for x in rep.signature]
    if rtl:
        cells = list(reversed(cells))
    t = Table([cells], colWidths=[width / len(cells)] * len(cells))
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 14)]))
    return [Spacer(1, 10), t]


def render_pdf(rep: Report, logo: bytes | None) -> bytes:
    _register()
    rtl = rep.rtl
    pal = Palette(rep.style)
    # Timetables with the days as rows are wide (8 period columns): landscape. With the days as columns
    # (5 columns, 8 period rows) a portrait page is taller and gives every period more room.
    grid_wide = bool(rep.grids) and (rep.layout == "rows" or len(rep.grids[0].days) > 6)
    wide = (grid_wide or any(len(t.columns) > 5 for t in rep.tables)) and rep.kind != "student-lists"
    pagesize = landscape(A4) if wide else A4
    st = _styles(rtl, pal)
    buf = io.BytesIO()
    top = 3.3 * cm if rep.letterhead else 1.3 * cm
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
        if not rep.letterhead:      # plain page (e.g. the school's printed letterhead paper): page footer only
            footer = f"{rep.generated_at}   ·   {'صفحة' if rtl else 'Page'} {canvas.getPageNumber()}"
            fp = Paragraph(rich(footer, rtl), st["foot"])
            fp.wrap(pw - doc.leftMargin - doc.rightMargin, 1 * cm)
            fp.drawOn(canvas, doc.leftMargin, 0.7 * cm)
            canvas.restoreState()
            return
        if logo_img:
            iw, ih = logo_img.getSize()
            h = 1.9 * cm
            w = iw * h / ih
            x = pw - doc.rightMargin - w if rtl else doc.leftMargin
            canvas.drawImage(logo_img, x, ph - 0.7 * cm - h, width=w, height=h, mask="auto", preserveAspectRatio=True)
        for text, size, bold, color in ((rep.school_name, 14, True, pal.accent), (rep.title, 12, True, colors.black),
                                        (" — ".join(x for x in (rep.timetable_name, rep.filters) if x), 9, False,
                                         colors.HexColor("#444444"))):
            p = Paragraph(rich(text, rtl, bold, pw - 2 * doc.leftMargin - 5.5 * cm, size), ParagraphStyle("h", fontName="DejaVu", fontSize=size, leading=size + 3,
                                                                alignment=TA_CENTER, textColor=color))
            _w, hgt = p.wrap(pw - 2 * doc.leftMargin - 5 * cm, 3 * cm)
            p.drawOn(canvas, doc.leftMargin + 2.5 * cm, y - hgt + size)
            y -= hgt + 1
        canvas.setStrokeColor(pal.accent)
        canvas.setLineWidth(1.2)
        canvas.line(doc.leftMargin, ph - top + 0.35 * cm, pw - doc.rightMargin, ph - top + 0.35 * cm)
        footer = f"{rep.generated_at}   ·   {'صفحة' if rtl else 'Page'} {canvas.getPageNumber()}"
        fp = Paragraph(rich(footer, rtl), st["foot"])
        fp.wrap(pw - doc.leftMargin - doc.rightMargin, 1 * cm)
        fp.drawOn(canvas, doc.leftMargin, 0.7 * cm)
        canvas.restoreState()

    story = []
    sign = _signature_flowable(rep, st, width)
    frame_h = pagesize[1] - top - doc.bottomMargin - 14      # the frame's own padding
    for i, g in enumerate(rep.grids):
        if i:
            story.append(PageBreak())
        # what the table may fill: the page minus its title, subtitle, footer line and signatures
        reserve = 1.0 * cm + (0.6 * cm if g.subtitle else 0) + (0.8 * cm if g.footer else 0) + (2.4 * cm if sign else 0)
        story += _grid_flowables(rep, g, st, width, pal, avail_h=frame_h - reserve)
        story += sign
    for i, t in enumerate(rep.tables):
        if i:
            story.append(PageBreak() if rep.kind == "student-lists" else Spacer(1, 14))
        story += _table_flowables(rep, t, st, width, pal)
    for n in rep.notes:
        story += [Spacer(1, 8), Paragraph(rich(n, rtl), st["foot"])]
    if rep.tables:
        story += sign
    if not story:
        story.append(Paragraph(rich("لا توجد بيانات مطابقة" if rtl else "No matching data", rtl), st["sub"]))
    doc.build(story, onFirstPage=header, onLaterPages=header)
    return buf.getvalue()
