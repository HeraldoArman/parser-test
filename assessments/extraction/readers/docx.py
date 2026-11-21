"""DOCX reader: body order preserved, merged cells deduplicated, styles mapped to heading hints."""
from __future__ import annotations

from docx import Document as open_docx
from docx.table import Table as DocxTable, _Cell
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn

from ..normalize import clean
from ..types import Block, Doc, Table

_HEADING_STYLES = ("heading", "title", "subtitle")


def _paragraph_block(paragraph: Paragraph) -> Block:
    style = (paragraph.style.name or "") if paragraph.style is not None else ""
    bold = any(run.bold for run in paragraph.runs) or style.lower().startswith(_HEADING_STYLES)
    return Block(text=clean(paragraph.text), bold=bold,
                 size=12.0 if style.lower().startswith(_HEADING_STYLES) else 0.0)


def _table_grid(table: DocxTable) -> list[list[str]]:
    """Grid text with horizontally merged cells expanded and vertical continuations blanked.

    Expanding by grid_span keeps the weight column aligned even on partially merged rows.
    """
    rows = []
    previous: set = set()
    for row in table.rows:
        cells: list[str] = []
        current: set = set()
        for tc in row._tr.tc_lst:
            current.add(tc)
            text = "" if tc in previous else clean(_Cell(tc, table).text)
            cells.append(text)
            cells.extend([""] * (tc.grid_span - 1))
        while cells and not cells[-1]:
            cells.pop()
        rows.append(cells)
        previous = current
    return rows


def read(path: str) -> Doc:
    document = open_docx(path)
    items = []
    order = 0
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            block = _paragraph_block(Paragraph(child, document))
            if block.text:
                block.order = order
                items.append(block)
                order += 1
        elif child.tag == qn("w:tbl"):
            grid = _table_grid(DocxTable(child, document))
            grid = [row for row in grid if any(row)]
            if len(grid) >= 2:
                items.append(Table(rows=grid, order=order))
                order += 1
    text_length = sum(len(i.text) for i in items if isinstance(i, Block))
    return Doc(items=items, page_count=0, text_length=text_length, suffix="docx")
