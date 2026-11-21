"""One entry point for extraction: file path -> document blocks + candidates + status."""
from __future__ import annotations

from . import candidates as candidate_finder
from .index import db_anchors
from .readers import fingerprint, read_document
from .readers import ocr
from . import ranker
from .validate import evaluate

EXTRACTOR_VERSION = "1.1"

STATUSES = ("parsed", "ok", "bonus", "ambiguous", "needs_review", "not_found", "failed")


def analyze(path: str, anchors: list[str] | None = None) -> dict:
    """Run the whole pipeline. Never raises for parse problems: returns a failed/needs_review dict."""
    try:
        doc = read_document(path)
    except Exception as exc:  # corrupt/unsupported file must not break a bulk upload
        return {
            "status": "failed", "error": f"{type(exc).__name__}: {exc}",
            "fingerprint": "", "candidates": [], "components": [], "reasons": [],
            "page_count": 0, "text_length": 0, "selected": None,
            "extractor_version": EXTRACTOR_VERSION,
        }

    if doc.scanned:
        return {
            "status": "needs_review", "error": "no text layer (scanned or image-only PDF)",
            "fingerprint": fingerprint(doc), "candidates": [], "components": [],
            "reasons": ["no extractable text"], "page_count": doc.page_count,
            "text_length": doc.text_length, "selected": None,
            "extractor_version": EXTRACTOR_VERSION,
        }

    if anchors is None:
        anchors = db_anchors()
    found = candidate_finder.find(doc, anchors=anchors)
    model = ranker.load()
    outcome = evaluate(found, model=model)
    selected = outcome["selected"]
    active = found[selected] if selected is not None and selected < len(found) else None

    reasons = list(outcome["reasons"])
    if doc.ocr_pages:
        reasons.insert(0, f"OCR used on {doc.ocr_pages} page(s)")
    if doc.ocr_limited:
        reasons.append(f"OCR stopped after {ocr.MAX_PAGES} pages; check the source for later pages")

    return {
        "status": outcome["status"],
        "error": "",
        "fingerprint": fingerprint(doc),
        "candidates": [c.to_dict() for c in found],
        "components": [c.to_dict() for c in active.components] if active else [],
        "reasons": reasons,
        "page_count": doc.page_count,
        "text_length": doc.text_length,
        "ocr_pages": doc.ocr_pages,
        "selected": selected,
        "extractor_version": EXTRACTOR_VERSION,
        "ranker_samples": int((model or {}).get("samples", 0)),
        "blocks": doc.to_json(),
    }
