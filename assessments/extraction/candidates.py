"""Layout-agnostic candidate discovery.

Every table and every run of consecutive percentage lines is a candidate. Candidates are scored
on structural evidence (numeric weight column, header vocabulary, plausibility of the weight sum),
never on a course-specific format, then ranked and deduplicated by their weight signature.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .components import (
    Component,
    WEIGHT_HEADER,
    _cell,
    _weight_ratio,
    from_lines,
    from_table,
    pick_weight_column,
)
from .index import similarity
from .normalize import clean, heading
from .types import Block, Doc, Table
from .weights import as_float

ASSESS_KEYS = re.compile(
    r"kuis|quiz|tugas|assignment|uts|uas|ujian|midterm|final|partisipasi|participation|"
    r"praktikum|\blab\b|proyek|project|case study|studi kasus|tutorial|hands-?on|responsi|"
    r"presentasi|portfolio|portofolio",
    re.I,
)
SKIP_HEADING = re.compile(
    r"peraturan|kejujuran|sanksi|rubrik|rubric|academic integrity|tata tertib|remedial|"
    r"pustaka|referensi|references|daftar pustaka",
    re.I,
)
SCHEDULE_HEADER = re.compile(
    r"minggu|tanggal|materi|topik|week|date|topic|jadwal|schedule|asinkron|praktikum|"
    r"lecture|tutorial|aktivitas|activities",
    re.I,
)
MIN_SCORE = 0.5


@dataclass
class Candidate:
    kind: str
    score: float
    components: list[Component]
    heading: str = ""
    page: int | None = None
    raw_section: str = ""
    reasons: list[str] = field(default_factory=list)
    total_row: float | None = None
    warnings: list[str] = field(default_factory=list)
    confidence: str = "medium"
    signals: dict = field(default_factory=dict)
    model_score: float | None = None

    @property
    def signature(self) -> tuple:
        weights = tuple(sorted(-1.0 if c.weight is None else round(c.weight, 2) for c in self.components))
        return weights + (len(self.components),)

    @property
    def total(self) -> float:
        return sum(c.weight or 0.0 for c in self.components)

    @property
    def plausible(self) -> bool:
        if len(self.components) < 2:
            return False
        if any(c.bonus for c in self.components):
            return True
        return abs(self.total - 100.0) <= 10.0

    def to_dict(self, include_components: bool = True) -> dict:
        data = {
            "kind": self.kind, "score": round(self.score, 3), "heading": self.heading,
            "page": self.page, "total": round(self.total, 2), "signature": list(self.signature),
            "reasons": self.reasons, "warnings": self.warnings, "confidence": self.confidence,
            "raw_section": self.raw_section[:8000],
            "total_row": self.total_row,
            "signals": self.signals,
            "model_score": None if self.model_score is None else round(self.model_score, 3),
        }
        if include_components:
            data["components"] = [c.to_dict() for c in self.components]
        return data


def _assessment_heading(text: str, anchors: list[str] | None) -> float:
    return similarity(text, anchors)


def _score_table(item: Table, heading_text: str, anchors: list[str] | None) -> Candidate | None:
    rows = [[clean(c) for c in row] for row in item.rows if any(clean(c) for c in row)]
    if len(rows) < 2:
        return None
    if item.ocr:
        # An OCR page grid mixes prose and tables; start at the row naming a weight.
        start = next((i for i, row in enumerate(rows)
                      if any(WEIGHT_HEADER.search(cell) for cell in row)), None)
        if start is None:
            return None
        rows = rows[start:]
        if len(rows) < 3:
            return None
    weight_col = pick_weight_column(rows)
    if weight_col is None:
        return None
    header = rows[0]
    header_match = bool(WEIGHT_HEADER.search(_cell(header, weight_col)))
    ratio = _weight_ratio([_cell(row, weight_col) for row in rows[1:]])
    components, meta = from_table(rows, source_ref=f"page {item.page}" if item.page else "")
    if len(components) < 2:
        return None
    # OCR grids are approximate: without a weight header they are usually a schedule.
    if item.ocr and not header_match:
        return None
    # Grade-conversion scales (A/A-/B+/...) are not assessment components.
    grade_like = sum(1 for c in components if re.fullmatch(r"[A-Fa-f][+-]?", c.name))
    if grade_like / len(components) > 0.5:
        return None

    reasons: list[str] = []
    score = 0.15
    if header_match:
        score += 0.35
        reasons.append(f"weight header {_cell(header, weight_col)!r}")
    if ratio >= 0.6:
        score += 0.3
        reasons.append(f"numeric weight column ({ratio:.0%})")
    elif ratio >= 0.4:
        score += 0.2
        reasons.append(f"mostly numeric weight column ({ratio:.0%})")
    if 2 <= len(components) <= 25:
        score += 0.15

    hits = sum(1 for c in components if ASSESS_KEYS.search(c.name))
    if hits:
        score += 0.15 if hits / len(components) >= 0.4 else 0.05
        reasons.append(f"{hits}/{len(components)} assessment-like names")

    total = sum(c.weight or 0.0 for c in components)
    if abs(total - 100) <= 0.5:
        score += 0.2
        reasons.append("weights sum to 100")
    elif abs(total - 100) <= 10:
        score += 0.1
        reasons.append(f"weights sum to {total:g}")
    if meta["total_row"] is not None:
        score += 0.1
        reasons.append(f"total row {meta['total_row']:g}")

    schedule_hits = sum(1 for cell in header if SCHEDULE_HEADER.search(cell))
    if schedule_hits >= 2:
        score -= 0.4
        reasons.append("schedule-like header")
    if len(header) > 8:
        score -= 0.1

    boost = _assessment_heading(heading_text, anchors)
    if boost:
        score += 0.15 * boost
        reasons.append(f"heading match {boost:.2f}")

    if meta["warnings"]:
        reasons.extend(meta["warnings"])
    return Candidate(
        kind="table", score=score, components=components, heading=heading_text, page=item.page,
        raw_section="\n".join(" | ".join(row) for row in rows),
        reasons=reasons, total_row=meta["total_row"], warnings=meta["warnings"],
        signals={
            "is_table": 1.0,
            "header_match": float(header_match),
            "numeric_ratio": ratio,
            "keyword_ratio": hits / len(components),
            "sum_exact": float(abs(total - 100) <= 0.5),
            "sum_close": float(abs(total - 100) <= 10),
            "has_total": float(meta["total_row"] is not None),
            "count": min(len(components) / 20.0, 1.0),
            "anchors": boost,
            "schedule": float(schedule_hits >= 2),
            "width": min(len(header) / 12.0, 1.0),
        },
    )


def _line_runs(doc: Doc):
    """Yield (blocks, heading_text) for each run of consecutive percentage lines."""
    from .components import match_line

    run: list[Block] = []
    current_heading = ""
    for item in doc.items:
        if isinstance(item, Table):
            if run:
                yield run, current_heading
                run = []
            continue
        if not item.text:
            continue
        # A weighted line can look like a heading ("UTS 33%"), so test it first.
        if match_line(item.text):
            run.append(item)
            continue
        if heading(item.text, item.bold, item.size):
            if run:
                yield run, current_heading
                run = []
            current_heading = item.text
            continue
        if run:
            yield run, current_heading
            run = []
    if run:
        yield run, current_heading


def _score_lines(blocks: list[Block], heading_text: str, anchors: list[str] | None) -> Candidate | None:
    from .components import match_line
    if len(blocks) < 2:
        return None
    if SKIP_HEADING.search(heading_text or ""):
        return None
    components, meta = from_lines(blocks, source_ref="")
    if len(components) < 2:
        return None
    reasons: list[str] = []
    names = [c.name for c in components]
    keyword_ratio = sum(1 for name in names if ASSESS_KEYS.search(name)) / len(names)
    if keyword_ratio < 0.34:
        return None
    label_ratio = sum(1 for name in names if len(name) <= 70 and not name.endswith(".")) / len(names)
    if label_ratio < 0.5:
        return None

    score = 0.2
    reasons.append(f"{len(components)} consecutive percentage lines")
    if len(components) >= 3:
        score += 0.1
    score += 0.3 * keyword_ratio
    if keyword_ratio:
        reasons.append(f"{keyword_ratio:.0%} assessment-like names")
    total = sum(c.weight or 0.0 for c in components)
    if abs(total - 100) <= 0.5:
        score += 0.25
        reasons.append("weights sum to 100")
    elif abs(total - 100) <= 10:
        score += 0.15
        reasons.append(f"weights sum to {total:g}")
    if meta["total_row"] is not None:
        score += 0.05
        reasons.append(f"total row {meta['total_row']:g}")
    boost = _assessment_heading(heading_text, anchors)
    if boost:
        score += 0.15 * boost
        reasons.append(f"heading match {boost:.2f}")
    if meta["warnings"]:
        reasons.extend(meta["warnings"])
    return Candidate(
        kind="lines", score=score, components=components, heading=heading_text,
        page=blocks[0].page, raw_section="\n".join(b.text for b in blocks),
        reasons=reasons, total_row=meta["total_row"], warnings=meta["warnings"],
        signals={
            "is_table": 0.0,
            "header_match": 0.0,
            "numeric_ratio": 1.0,
            "keyword_ratio": keyword_ratio,
            "sum_exact": float(abs(total - 100) <= 0.5),
            "sum_close": float(abs(total - 100) <= 10),
            "has_total": float(meta["total_row"] is not None),
            "count": min(len(components) / 20.0, 1.0),
            "anchors": boost,
            "schedule": 0.0,
            "width": 0.0,
        },
    )


def find(doc: Doc, anchors: list[str] | None = None, limit: int = 5) -> list[Candidate]:
    anchors = anchors or []
    candidates: list[Candidate] = []
    current_heading = ""
    for item in doc.items:
        if isinstance(item, Block):
            if heading(item.text, item.bold, item.size):
                current_heading = item.text
            continue
        if SKIP_HEADING.search(current_heading or ""):
            continue
        candidate = _score_table(item, current_heading, anchors)
        if candidate:
            candidates.append(candidate)
    for blocks, heading_text in _line_runs(doc):
        if SKIP_HEADING.search(heading_text or ""):
            continue
        candidate = _score_lines(blocks, heading_text, anchors)
        if candidate:
            candidates.append(candidate)

    # Deduplicate identical weight signatures, keeping the best-scoring representation.
    by_signature: dict[tuple, Candidate] = {}
    for candidate in candidates:
        key = candidate.signature
        if key not in by_signature or candidate.score > by_signature[key].score:
            by_signature[key] = candidate
    ranked = sorted(by_signature.values(), key=lambda c: c.score, reverse=True)
    kept = [c for c in ranked if c.score >= MIN_SCORE][:limit]
    if not kept and ranked:
        kept = ranked[:1]
    for candidate in kept:
        candidate.confidence = "high" if candidate.score >= 0.9 else "medium"
    return kept
