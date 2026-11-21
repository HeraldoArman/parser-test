"""XLSX reader: every sheet becomes one grid table, sheet name becomes a heading block."""
from __future__ import annotations

from openpyxl import load_workbook

from ..normalize import clean
from ..types import Block, Doc, Table


def read(path: str) -> Doc:
    workbook = load_workbook(path, read_only=True, data_only=True)
    items = []
    order = 0
    text_length = 0
    for index, sheet in enumerate(workbook.worksheets, start=1):
        name = clean(sheet.title)
        if name:
            items.append(Block(text=name, page=index, order=order, bold=True))
            text_length += len(name)
            order += 1
        rows = []
        for row in sheet.iter_rows(values_only=True):
            cells = [clean("" if v is None else str(v)) for v in row]
            if any(cells):
                rows.append(cells)
        if len(rows) >= 2:
            items.append(Table(rows=rows, page=index, order=order))
            order += 1
    workbook.close()
    return Doc(items=items, page_count=len(items), text_length=text_length, suffix="xlsx")
