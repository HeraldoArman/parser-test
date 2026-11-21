"""PDF reader: words -> lines -> blocks, plus table grids. Everything keeps page provenance."""
from __future__ import annotations

import pdfplumber

from ..normalize import clean
from ..types import Block, Doc, Table
from . import ocr

_TABLE_FALLBACK = {"vertical_strategy": "text", "horizontal_strategy": "text"}


def _group_lines(words: list[dict]) -> list[dict]:
    lines: list[dict] = []
    for word in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        if lines and abs(word["top"] - lines[-1]["top"]) <= 2.5:
            lines[-1]["words"].append(word)
            lines[-1]["top"] = (lines[-1]["top"] + word["top"]) / 2
        else:
            lines.append({"top": word["top"], "words": [word]})
    result = []
    for line in lines:
        parts = sorted(line["words"], key=lambda w: w["x0"])
        result.append({
            "top": line["top"],
            "text": clean(" ".join(p["text"] for p in parts)),
            "size": max((p.get("size") or 0) for p in parts),
            "bold": any("Bold" in (p.get("fontname") or "") or "bold" in (p.get("fontname") or "")
                        for p in parts),
        })
    return result


def read(path: str) -> Doc:
    items: list[tuple[float, int, object]] = []
    text_length = 0
    ocr_pages = 0
    ocr_limited = False
    ocr_budget = ocr.MAX_PAGES if ocr.available() else 0
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            text_length += len(text)
            words = page.extract_words(extra_attrs=["size", "fontname"], keep_blank_chars=False)
            lines = _group_lines(words)

            tables = []
            try:
                tables = page.find_tables()
            except Exception:
                tables = []
            if not tables and text.count("%") >= 3:
                try:
                    tables = page.find_tables(table_settings=_TABLE_FALLBACK)
                except Exception:
                    tables = []

            for table in tables:
                rows = [[clean(cell) for cell in row] for row in table.extract()]
                rows = [row for row in rows if any(row)]
                if len(rows) < 2:
                    continue
                item = Table(rows=rows, page=pno)
                items.append((table.bbox[1], pno, item))

            # Image-only page: OCR gives us both lines and a rough column grid.
            if len(text.strip()) < 40 and ocr.available():
                if ocr_budget > 0:
                    ocr_budget -= 1
                    try:
                        image = page.to_image(resolution=200).original
                        ocr_lines, grid = ocr.read_page(image)
                    except Exception:
                        ocr_lines, grid = [], []
                    if ocr_lines:
                        ocr_pages += 1
                        text_length += sum(len(line) for line in ocr_lines)
                        for rows in grid:
                            items.append((0.0, pno, Table(rows=rows, page=pno, ocr=True)))
                        for offset, line in enumerate(ocr_lines):
                            items.append((offset * 10.0, pno, Block(
                                text=clean(line), page=pno, order=offset)))
                        lines = []  # the text layer gave us nothing usable
                else:
                    ocr_limited = True

            # Text lines are kept even inside table boxes: pdfplumber fragments borderless
            # tables, and dropping those lines loses real content. Duplicate candidates are
            # deduplicated later by weight signature.
            for line in lines:
                if not line["text"] or len(line["text"]) > 400:
                    continue
                items.append((line["top"], pno, Block(
                    text=line["text"], page=pno, size=line["size"], bold=line["bold"],
                )))

    items.sort(key=lambda row: (row[1], row[0]))
    ordered = []
    for order, (_, _, item) in enumerate(items):
        item.order = order
        ordered.append(item)
    return Doc(items=ordered, page_count=pno if items else 0, text_length=text_length,
               suffix="pdf", ocr_pages=ocr_pages, ocr_limited=ocr_limited)
