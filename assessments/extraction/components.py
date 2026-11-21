"""Row extraction from a table grid or a percentage line-run, plus component classification."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .normalize import clean, strip_leading, strip_trailing_punct
from .types import Block
from .weights import Weight, parse_weight

NAME_STRONG = re.compile(
    r"komponen|component|assessment|evaluasi|evaluation|bentuk|kriteria|criterion|"
    r"name|nama|description|deskripsi|item|aktivitas", re.I)
NAME_WEAK = re.compile(r"instrument|instrumen|jenis|tipe|type|metode|method|frekuensi|frequency", re.I)
TYPE_HEADER = re.compile(
    r"evaluasi|evaluation|bentuk|jenis|tipe|type|instrumen|instrument|metode|method|activity", re.I)
WEIGHT_HEADER = re.compile(r"bobot|weight|persen|%|nilai|score|kontribusi|porsi", re.I)
TOTAL = re.compile(r"^(total|jumlah|sum|total bobot|total nilai)$", re.I)
NUMERIC = re.compile(r"^[\d\s.,%()\u2013\u2014\-+/x\u00d7@]+$")

KIND_RULES = [
    ("midterm", re.compile(r"\buts\b|midterm|mid-term|tengah semester", re.I)),
    ("final", re.compile(r"\buas\b|final|akhir semester", re.I)),
    ("quiz", re.compile(r"kuis|quiz", re.I)),
    ("participation", re.compile(r"partisipasi|participation|keaktifan|kehadiran|attendance", re.I)),
    ("project", re.compile(r"proyek|project|case study|studi kasus", re.I)),
    ("lab", re.compile(r"praktikum|lab\b|laboratorium|laboratory|hands-?on|tutorial", re.I)),
    ("assignment", re.compile(r"tugas|assignment|homework|responsi", re.I)),
    ("exam", re.compile(r"ujian|exam", re.I)),
]


@dataclass
class Component:
    name: str
    kind: str = "other"
    weight: float | None = None
    raw_weight: str = ""
    formula: str = ""
    note: str = ""
    source_ref: str = ""
    confidence: str = "medium"
    bonus: bool = False
    is_range: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind, "weight": self.weight,
            "raw_weight": self.raw_weight, "formula": self.formula, "note": self.note,
            "source_ref": self.source_ref, "confidence": self.confidence,
            "bonus": self.bonus, "is_range": self.is_range,
        }


def classify(name: str) -> str:
    for kind, pattern in KIND_RULES:
        if pattern.search(name):
            return kind
    return "other"


def _cell(row: list[str], index: int) -> str:
    return clean(row[index]) if index < len(row) else ""


def _column(rows: list[list[str]], index: int) -> list[str]:
    return [_cell(row, index) for row in rows[1:]]


def _weight_ratio(values: list[str]) -> float:
    filled = [v for v in values if v and re.search(r"\d", v)]
    if not filled:
        return 0.0
    parsed = [parse_weight(v) for v in filled]
    ok = sum(1 for w in parsed if w is not None and w.value is not None)
    return ok / len(filled)


def pick_weight_column(rows: list[list[str]]) -> int | None:
    width = max((len(r) for r in rows), default=0)
    header = rows[0] if rows else []
    best, best_score = None, 0.0
    for index in range(width):
        ratio = _weight_ratio(_column(rows, index))
        header_match = bool(WEIGHT_HEADER.search(_cell(header, index)))
        score = (2.0 if header_match else 0.0) + ratio
        if ratio < 0.35 and not (header_match and ratio >= 0.2):
            continue
        if score > best_score:
            best, best_score = index, score
    return best


def pick_name_column(rows: list[list[str]], weight_col: int) -> int | None:
    width = max((len(r) for r in rows), default=0)
    header = rows[0] if rows else []
    best, best_score = None, -1e9
    for index in range(width):
        if index == weight_col:
            continue
        values = [v for v in _column(rows, index) if v]
        if not values:
            continue
        head = _cell(header, index)
        average = sum(len(v) for v in values) / len(values)
        numericish = sum(1 for v in values if NUMERIC.match(v)) / len(values)
        score = (2.0 if NAME_STRONG.search(head) else 0.0)
        score += (1.0 if NAME_WEAK.search(head) else 0.0)
        score += min(average, 80) / 100.0 - numericish
        if score > best_score:
            best, best_score = index, score
    return best


def _type_column(rows: list[list[str]], weight_col: int, name_col: int) -> int | None:
    width = max((len(r) for r in rows), default=0)
    header = rows[0] if rows else []
    for index in range(width):
        if index in (weight_col, name_col):
            continue
        if not TYPE_HEADER.search(_cell(header, index)):
            continue
        values = [v for v in _column(rows, index) if v]
        if values and sum(len(v) for v in values) / len(values) <= 28:
            return index
    return None


def from_table(rows: list[list[str]], source_ref: str = "") -> tuple[list[Component], dict]:
    """Return (components, meta) where meta carries total_row and warnings."""
    rows = [[clean(c) for c in row] for row in rows if any(clean(c) for c in row)]
    meta = {"total_row": None, "warnings": []}
    if len(rows) < 2:
        return [], {"total_row": None, "warnings": ["table too small"]}

    weight_col = pick_weight_column(rows)
    if weight_col is None:
        return [], {"total_row": None, "warnings": ["no numeric weight column"]}
    name_col = pick_name_column(rows, weight_col)
    type_col = _type_column(rows, weight_col, name_col) if name_col is not None else None
    header = rows[0]

    components: list[Component] = []
    for offset, row in enumerate(rows[1:], start=1):
        if [clean(c) for c in row] == header:
            continue
        raw = _cell(row, weight_col)
        parsed = parse_weight(raw)
        if parsed is None or (parsed.value is None and not parsed.is_range):
            # continuation of the previous row (wrapped description or extra notes)
            extra = " ".join(c for i, c in enumerate(row) if i not in (weight_col,) and c)
            extra = strip_trailing_punct(clean(extra))
            if components and extra and not NUMERIC.match(extra):
                components[-1].note = clean(f"{components[-1].note} {extra}")
            continue
        name = _cell(row, name_col) if name_col is not None else ""
        name = strip_trailing_punct(strip_leading(name))
        if not name:
            others = [c for i, c in enumerate(row) if i != weight_col and c]
            name = strip_trailing_punct(strip_leading(max(others, key=len))) if others else ""
        if not name:
            continue
        if TOTAL.match(name):
            meta["total_row"] = float(parsed.value) if parsed.value is not None else None
            continue
        if parsed.is_range or parsed.value is None:
            meta["warnings"].append(f"unparseable weight: {raw!r}")
        name_header = _cell(header, name_col) if name_col is not None else ""
        if type_col is not None and not TYPE_HEADER.search(name_header):
            prefix = strip_trailing_punct(clean(_cell(row, type_col)))
            if prefix and len(prefix) <= 28 and prefix.lower() not in name.lower():
                name = f"{prefix}: {name}"
        components.append(Component(
            name=name,
            kind=classify(name),
            weight=float(parsed.value) if parsed.value is not None else None,
            raw_weight=raw,
            formula=parsed.formula,
            source_ref=f"{source_ref} table row {offset + 1}",
            bonus=parsed.bonus or "bonus" in name.lower(),
            is_range=parsed.is_range,
        ))
    if len(components) < 2:
        meta["warnings"].append("fewer than two components")
    return components, meta


LINE_RE = re.compile(r"^(?P<name>.+?)(?P<num>\d{1,3}(?:[.,]\d+)?)\s*%\s*$")


def match_line(text: str) -> tuple[str, Weight] | None:
    text = clean(text)
    if len(text) > 300 or text.count("%") != 1:
        return None
    match = LINE_RE.match(text)
    if not match:
        return None
    parsed = parse_weight(match.group("num") + "%")
    if parsed is None or parsed.value is None:
        return None
    name = strip_trailing_punct(strip_leading(match.group("name")))
    name = strip_trailing_punct(re.sub(r"\s*[:\-\u2013\u2014]\s*$", "", name))
    if not name or len(name) < 2:
        return None
    return name, parsed


def from_lines(blocks: list[Block], source_ref: str = "") -> tuple[list[Component], dict]:
    components: list[Component] = []
    meta = {"total_row": None, "warnings": []}
    for offset, block in enumerate(blocks):
        matched = match_line(block.text)
        if not matched:
            continue
        name, parsed = matched
        if TOTAL.match(name):
            meta["total_row"] = float(parsed.value) if parsed.value is not None else None
            continue
        components.append(Component(
            name=name,
            kind=classify(name),
            weight=float(parsed.value) if parsed.value is not None else None,
            raw_weight=parsed.raw,
            formula=parsed.formula,
            source_ref=f"{source_ref} line {block.order + 1}",
            bonus=parsed.bonus or "bonus" in name.lower(),
            is_range=parsed.is_range,
        ))
    components = _drop_nested_codes(components, meta)
    if len(components) < 2:
        meta["warnings"].append("fewer than two components")
    return components, meta


_NESTED_CODE = re.compile(r"^(?:[A-Z]{1,4}\d{1,3}|Phase\s*\d+|Week\s*\d+|Pertemuan\s*\d+)$", re.I)


def _drop_nested_codes(components: list[Component], meta: dict) -> list[Component]:
    """A section that lists category totals and then their per-item breakdown double counts.

    Keeps the aggregates when the run is over 105% and at least three rows look like
    'Category (3)' totals; the coded detail rows (H01, Phase 2, ...) are dropped.
    """
    total = sum(c.weight or 0.0 for c in components)
    aggregates = sum(1 for c in components if re.search(r"\(\d+\)$", c.name))
    if total <= 105 or aggregates < 3:
        return components
    kept = [c for c in components if not _NESTED_CODE.match(c.name)]
    if len(kept) < 2:
        return components
    meta["warnings"].append("nested item codes dropped in favour of category totals")
    return kept
