"""Ingest services: hashing, parsing, candidate materialisation."""
import hashlib

from .extraction.index import db_anchors
from .extraction.pipeline import analyze
from .models import Component, Document


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sync_components(document: Document, index: int | None = None) -> None:
    """Materialise the selected candidate's rows as editable Component records."""
    index = document.selected if index is None else index
    document.components.all().delete()
    candidates = document.candidates
    if index is None or not (0 <= index < len(candidates)):
        return
    rows = candidates[index].get("components", [])
    Component.objects.bulk_create([
        Component(
            document=document, order=order, name=row.get("name", "")[:300],
            kind=row.get("kind", "other"), weight=row.get("weight"),
            raw_weight=row.get("raw_weight", "")[:120], formula=row.get("formula", "")[:120],
            note=row.get("note", ""), source_ref=row.get("source_ref", "")[:120],
            confidence=row.get("confidence", "medium"), bonus=row.get("bonus", False),
            is_range=row.get("is_range", False),
        )
        for order, row in enumerate(rows)
    ])


def parse_document(document: Document, force: bool = False) -> None:
    path = document.file.path
    if not document.sha256:
        document.sha256 = sha256_of(path)
    twin = None if force else (
        Document.objects.filter(sha256=document.sha256).exclude(pk=document.pk)
        .exclude(result={}).first()
    )
    if twin:
        # Identical file already parsed: reuse the result instead of paying for it twice.
        document.status = twin.status
        document.error = twin.error
        document.fingerprint = twin.fingerprint
        document.blocks = twin.blocks
        document.result = twin.result
        document.extractor_version = twin.extractor_version
        document.selected = twin.selected
    else:
        result = analyze(path, anchors=db_anchors())
        document.blocks = result.pop("blocks", [])
        document.status = result.get("status", "failed")
        document.error = result.get("error", "")
        document.fingerprint = result.get("fingerprint", "")
        document.result = result
        document.extractor_version = result.get("extractor_version", "")
        document.selected = result.get("selected")
    document.save()
    sync_components(document)
