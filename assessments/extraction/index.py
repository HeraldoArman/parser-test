"""Growing section-label index.

Approved documents contribute their assessment heading; candidate headings are scored by
token overlap with that index. No model, no network, and it improves as the corpus is reviewed.
"""
from __future__ import annotations

from .normalize import tokens

SEED_HEADINGS = [
    "komponen penilaian",
    "komponen dan bobot",
    "kriteria penilaian",
    "sistem penilaian",
    "bobot penilaian",
    "rubrik penilaian",
    "evaluasi",
    "penilaian",
    "asesmen",
    "marking criteria",
    "assessment",
    "evaluation",
    "grading",
    "assessment components",
]


def similarity(text: str, anchors: list[str] | None = None) -> float:
    """Best token-overlap score between `text` and the anchor headings."""
    text_tokens = tokens(text)
    if not text_tokens:
        return 0.0
    best = 0.0
    for anchor in anchors or SEED_HEADINGS:
        anchor_tokens = tokens(anchor)
        if not anchor_tokens:
            continue
        overlap = len(text_tokens & anchor_tokens) / len(text_tokens | anchor_tokens)
        best = max(best, overlap)
    return best


def db_anchors() -> list[str]:
    """Anchors stored by reviewers; empty outside a configured Django app."""
    try:
        from ..models import AnchorEntry
        return list(AnchorEntry.objects.values_list("text", flat=True))
    except Exception:
        return []
