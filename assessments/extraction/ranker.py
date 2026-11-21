"""Learned candidate ranker, trained only from human approvals.

Deliberately tiny: logistic regression over the structural signals that the
rule scorer already computes. No dependency beyond the standard library, no
network, and the file is small enough to read in review. Until enough
approvals exist the rule score alone decides; the model can only reorder
candidates inside the same validation tier, never promote a candidate that
the rules reject.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .candidates import Candidate

FEATURES = (
    "is_table",
    "header_match",
    "numeric_ratio",
    "keyword_ratio",
    "sum_exact",
    "sum_close",
    "has_total",
    "count",
    "anchors",
    "schedule",
    "width",
)
MIN_SAMPLES = 20
MIN_POSITIVES = 5


def vector(candidate: Candidate) -> list[float]:
    signals = candidate.signals or {}
    return [float(signals.get(name, 0.0)) for name in FEATURES]


def _sigmoid(z: float) -> float:
    if z < -30:
        return 0.0
    if z > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def predict_vector(model: dict, values: list[float]) -> float:
    weights = model.get("weights") or []
    if len(weights) != len(values):
        return 0.5
    z = float(model.get("bias", 0.0))
    for weight, value in zip(weights, values):
        z += weight * value
    return _sigmoid(z)


def predict(model: dict, candidate: Candidate) -> float:
    return predict_vector(model, vector(candidate))


def fit(rows: list[list[float]], labels: list[int], epochs: int = 600, rate: float = 0.3) -> dict:
    """Batch gradient descent; enough for a few hundred samples and 11 features."""
    weights = [0.0] * len(FEATURES)
    bias = 0.0
    count = max(len(rows), 1)
    for _ in range(epochs):
        gradients = [0.0] * len(FEATURES)
        gradient_bias = 0.0
        for row, label in zip(rows, labels):
            error = _sigmoid(bias + sum(w * x for w, x in zip(weights, row))) - label
            for index, value in enumerate(row):
                gradients[index] += error * value
            gradient_bias += error
        for index in range(len(weights)):
            weights[index] -= rate * gradients[index] / count
        bias -= rate * gradient_bias / count
    return {
        "features": list(FEATURES),
        "weights": [round(w, 6) for w in weights],
        "bias": round(bias, 6),
        "samples": len(rows),
        "positives": sum(labels),
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def path() -> Path:
    try:
        from django.conf import settings
        return Path(getattr(settings, "RANKER_PATH", settings.BASE_DIR / "ranker.json"))
    except Exception:
        return Path("ranker.json")


def load() -> dict | None:
    target = path()
    try:
        model = json.loads(target.read_text())
    except (OSError, ValueError):
        return None
    if model.get("features") != list(FEATURES) or model.get("samples", 0) < MIN_SAMPLES:
        return None
    return model


def save(model: dict) -> Path:
    target = path()
    target.write_text(json.dumps(model, indent=2))
    return target
