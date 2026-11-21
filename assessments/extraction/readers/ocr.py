"""OCR fallback for PDF pages without a text layer.

RapidOCR (ONNX) is bundled with its models, so no system toolchain is needed.
Boxes are grouped into lines and, when the x-gaps are wide, into cells so the
normal table detector can still see a grid.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_PAGES = 40
MIN_SCORE = 0.45
CELL_GAP = 28  # pixels at 200 dpi

_engine = None


def available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def _load():
    global _engine
    if _engine is None:
        import os
        from rapidocr_onnxruntime import RapidOCR
        # OCR is the only CPU-heavy step; bound it so one upload cannot starve the box.
        threads = max(1, int(os.environ.get("OCR_THREADS", "4")))
        _engine = RapidOCR(intra_op_num_threads=threads, inter_op_num_threads=1)
    return _engine


@dataclass
class Box:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


def _boxes(image) -> list[Box]:
    result, _ = _load()(image)
    boxes = []
    for corners, text, score in result or []:
        text = (text or "").strip()
        if not text or score < MIN_SCORE:
            continue
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        boxes.append(Box(text=text, x0=min(xs), x1=max(xs), top=min(ys), bottom=max(ys)))
    return boxes


def lines(boxes: list[Box]) -> list[list[Box]]:
    """Group boxes that share a vertical band, tolerant of OCR jitter."""
    grouped: list[list[Box]] = []
    for box in sorted(boxes, key=lambda b: ((b.top + b.bottom) / 2, b.x0)):
        centre = (box.top + box.bottom) / 2
        if grouped:
            last = grouped[-1]
            last_centre = sum((b.top + b.bottom) / 2 for b in last) / len(last)
            height = max(b.bottom - b.top for b in last)
            if abs(centre - last_centre) <= max(8.0, height * 0.6):
                last.append(box)
                continue
        grouped.append([box])
    return [sorted(line, key=lambda b: b.x0) for line in grouped]


def columns(boxes: list[Box], gap: float = CELL_GAP) -> list[float]:
    """Cluster left edges into column anchors, tolerant of OCR x-jitter."""
    anchors: list[float] = []
    for x0 in sorted(b.x0 for b in boxes):
        if not anchors or x0 - anchors[-1] > gap:
            anchors.append(x0)
    return anchors


def cells(line: list[Box], anchors: list[float]) -> list[str]:
    """Place a line's boxes into the page column grid, blank where a column is absent."""
    out = [""] * len(anchors)
    for box in line:
        index = max((i for i, x in enumerate(anchors) if box.x0 >= x - 1), default=0)
        out[index] = f"{out[index]} {box.text}".strip()
    while out and not out[-1]:
        out.pop()
    return out


def runs(grid: list[list[str]], minimum: int = 3) -> list[list[list[str]]]:
    """Split a page grid into table-like runs; a single-cell line ends the run."""
    out: list[list[list[str]]] = []
    current: list[list[str]] = []
    for row in grid:
        filled = [cell for cell in row if cell.strip()]
        if len(filled) >= 2:
            current.append(row)
            continue
        if len(current) >= minimum:
            out.append(current)
        current = []
    if len(current) >= minimum:
        out.append(current)
    return out


def read_page(image) -> tuple[list[str], list[list[list[str]]]]:
    """Return (text lines, table-like row runs) for one rendered page."""
    found = lines(_boxes(image))
    text_lines = [" ".join(b.text for b in line) for line in found]
    anchors = columns([b for line in found for b in line])
    grid = [cells(line, anchors) for line in found if len(line) >= 2]
    return text_lines, runs(grid)
