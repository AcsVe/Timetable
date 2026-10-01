"""Excel export: real data cells (not pictures), right-to-left sheets for Arabic, logo in the header."""
from __future__ import annotations

import io
import re

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.reports.data import Grid, Report, Table, grid_matrix

THIN = Side(style="thin", color="B8C2D0")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill("solid", fgColor="1F4E8C")
SUB_FILL = PatternFill("solid", fgColor="E8EEF7")
MISSING_FILL = PatternFill("solid", fgColor="EEEEEE")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
HEADER_ROWS = 5


def _sheet_title(name: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "-", name)[:28] or "Sheet"
    title, i = base, 2
    while title in used:
        title = f"{base[:25]} {i}"
        i += 1
    used.add(title)
    return title


def _header(ws, rep: Report, sub_title: str, width_cols: int, logo: bytes | None):
    ws.sheet_view.rightToLeft = rep.rtl
    font = "Arial"
    first = 2 if logo else 1
    last = max(width_cols, first + 2)
    for row, text, size, bold in ((1, rep.school_name, 14, True), (2, rep.title, 13, True),
                                  (3, sub_title, 11, True),
                                  (4, " — ".join(x for x in (rep.timetable_name, rep.filters, rep.generated_at) if x), 9, False)):
        ws.merge_cells(start_row=row, start_column=first, end_row=row, end_column=last)
        c = ws.cell(row=row, column=first, value=text)
        c.font = Font(name=font, size=size, bold=bold, color="1F4E8C" if row < 3 else "333333")
        c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 24
    if logo:
        try:
            img = XLImage(io.BytesIO(logo))
            ratio = 70 / max(img.height, 1)
            img.height, img.width = 70, int(img.width * ratio)
            ws.add_image(img, "A1")
            ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width or 0, img.width / 7)
        except Exception:
            pass
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{HEADER_ROWS + 1}:{HEADER_ROWS + 1}"


def _rich_cell(entries):
    """Subject in bold, teacher/room under it in a smaller grey font (Excel rich text)."""
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.cell.text import InlineFont
    bold = InlineFont(rFont="Arial", b=True, sz=10)
    small = InlineFont(rFont="Arial", sz=8, color="555555")
    parts = []
    for e in entries:
        lines = [x for x in e if x]
        if not lines:
            continue
        if parts:
            parts.append(TextBlock(small, "\n"))
        parts.append(TextBlock(bold, lines[0]))
        for x in lines[1:]:
            parts.append(TextBlock(small, "\n" + x))
    return CellRichText(*parts) if parts else None


def _write_grid(ws, rep: Report, g: Grid, logo):
    corner, heads, rows = grid_matrix(g, rep.layout, rep.rtl, raw=True)
    _header(ws, rep, g.title + (f" — {g.subtitle}" if g.subtitle else ""), len(heads) + 1, logo)
    r0 = HEADER_ROWS + 1
    for j, text in enumerate([corner] + heads, start=1):
        c = ws.cell(row=r0, column=j, value=text)
        c.font, c.fill, c.alignment, c.border = Font(name="Arial", bold=True, color="FFFFFF"), HEAD_FILL, CENTER, BORDER
    ws.row_dimensions[r0].height = 32 if rep.layout == "rows" else 18
    for i, (label, cells, missing) in enumerate(rows, start=1):
        row = r0 + i
        c = ws.cell(row=row, column=1, value=label)
        c.font, c.fill, c.alignment, c.border = Font(name="Arial", bold=True), SUB_FILL, CENTER, BORDER
        max_lines = 2
        for j, (text, miss) in enumerate(zip(cells, missing), start=2):
            cell = ws.cell(row=row, column=j)
            cell.alignment, cell.border = CENTER, BORDER
            if miss:
                cell.fill = MISSING_FILL
                continue
            cell.font = Font(name="Arial", size=9)
            if text:
                cell.value = _rich_cell(text)
                max_lines = max(max_lines, sum(len([x for x in e if x]) for e in text))
        ws.row_dimensions[row].height = 15 * max_lines
    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width or 0, 13)
    for j in range(len(heads)):
        ws.column_dimensions[get_column_letter(j + 2)].width = 16 if rep.layout == "rows" else 24
    if g.footer:
        ws.cell(row=r0 + len(rows) + 2, column=1, value=g.footer).font = Font(name="Arial", italic=True)


def _write_table(ws, rep: Report, t: Table, logo):
    _header(ws, rep, t.title, len(t.columns), logo)
    r0 = HEADER_ROWS + 1
    for j, text in enumerate(t.columns, start=1):
        c = ws.cell(row=r0, column=j, value=text)
        c.font, c.fill, c.alignment, c.border = Font(name="Arial", bold=True, color="FFFFFF"), HEAD_FILL, CENTER, BORDER
    rows = list(t.rows) + ([t.totals] if t.totals else [])
    for i, row in enumerate(rows, start=1):
        is_total = t.totals is not None and i == len(rows)
        for j, v in enumerate(row, start=1):
            c = ws.cell(row=r0 + i, column=j, value=v)
            c.border = BORDER
            c.font = Font(name="Arial", bold=is_total or j == 1)
            if is_total:
                c.fill = SUB_FILL
            if (j - 1) in t.percent and isinstance(v, (int, float)):
                c.number_format = "0%"
            c.alignment = Alignment(horizontal="center" if (j - 1) in t.numeric | t.percent else ("right" if rep.rtl else "left"),
                                    vertical="center", wrap_text=True)
    for j, col in enumerate(t.columns, start=1):
        longest = max([len(str(col))] + [len(str(r[j - 1] or "")) for r in rows])
        ws.column_dimensions[get_column_letter(j)].width = min(max(10, longest + 2), 60)
    ws.freeze_panes = ws.cell(row=r0 + 1, column=2)
    if t.rows:
        ws.auto_filter.ref = f"A{r0}:{get_column_letter(len(t.columns))}{r0 + len(t.rows)}"


def render_xlsx(rep: Report, logo: bytes | None) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    for g in rep.grids:
        _write_grid(wb.create_sheet(_sheet_title(g.title.split(": ", 1)[-1], used)), rep, g, logo)
    for t in rep.tables:
        _write_table(wb.create_sheet(_sheet_title(rep.title, used)), rep, t, logo)
    if not wb.sheetnames:
        ws = wb.create_sheet(_sheet_title(rep.title, used))
        _header(ws, rep, "لا توجد بيانات مطابقة" if rep.rtl else "No matching data", 4, logo)
    wb.properties.title = rep.title
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
