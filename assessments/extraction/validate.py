"""Validation gate: decides status and which candidate prefills the review form."""
from __future__ import annotations

from .candidates import Candidate
from . import ranker

THRESHOLD = 0.5      # below this a candidate is not trusted to prefill
LOW_THRESHOLD = 0.45  # below this we call the document "not found" rather than "needs review"


def _exact(candidate: Candidate) -> bool:
    if any(c.weight is None for c in candidate.components):
        return False
    return abs(candidate.total - 100.0) <= 0.5


def _bonus_ok(candidate: Candidate) -> bool:
    if not any(c.bonus for c in candidate.components):
        return False
    base = sum(c.weight or 0.0 for c in candidate.components if not c.bonus)
    return abs(base - 100.0) <= 0.5


def _rank(candidate: Candidate, model: dict | None = None) -> tuple:
    if _exact(candidate):
        tier = 0
    elif _bonus_ok(candidate):
        tier = 1
    elif candidate.plausible:
        tier = 2
    else:
        tier = 3
    # The learned score only breaks ties inside a tier; the rules still gate.
    blended = candidate.score
    if model:
        candidate.model_score = ranker.predict(model, candidate)
        blended += 0.5 * candidate.model_score
    return (tier, -blended)


def evaluate(candidates: list[Candidate], threshold: float = THRESHOLD,
             model: dict | None = None) -> dict:
    if not candidates:
        return {"status": "not_found", "selected": None, "candidates": [],
                "reasons": ["no table or percentage list detected"]}

    if candidates[0].score < LOW_THRESHOLD:
        return {"status": "not_found", "selected": None, "candidates": candidates,
                "reasons": ["only low-confidence candidates found (no assessment section)"]}

    usable = [c for c in candidates if c.score >= threshold and len(c.components) >= 2]
    if not usable:
        best = candidates[0]
        return {"status": "needs_review", "selected": candidates.index(best),
                "candidates": candidates,
                "reasons": ["candidates found but below confidence threshold"]}

    plausible = [c for c in usable if c.plausible]
    selected = min(usable, key=lambda c: _rank(c, model))
    selected_index = candidates.index(selected)

    if len(plausible) >= 2:
        reason = "two different plausible representations: " + "; ".join(
            f"{c.kind} {len(c.components)} items / {c.total:g}%" for c in plausible[:3])
        return {"status": "ambiguous", "selected": selected_index, "candidates": candidates,
                "reasons": [reason, "pick the representation that matches the course assessment plan"]}

    reasons = list(selected.reasons[:4])
    if not selected.plausible:
        reasons.append(f"weights sum to {selected.total:g}, expected 100")
        return {"status": "needs_review", "selected": selected_index,
                "candidates": candidates, "reasons": reasons}
    if _exact(selected):
        return {"status": "ok", "selected": selected_index, "candidates": candidates,
                "reasons": reasons}
    if _bonus_ok(selected):
        reasons.append("bonus component excluded from the 100% base")
        return {"status": "bonus", "selected": selected_index, "candidates": candidates,
                "reasons": reasons}
    return {"status": "needs_review", "selected": selected_index,
            "candidates": candidates, "reasons": reasons}
