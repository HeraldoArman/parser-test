"""Reader dispatch and structural fingerprinting."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..normalize import clean, heading
from ..types import Block, Doc, Table
from . import docx as docx_reader
from . import pdf as pdf_reader
from . import xlsx as xlsx_reader

READERS = {
    "pdf": pdf_reader.read,
    "docx": docx_reader.read,
    "xlsx": xlsx_reader.read,
}
SUPPORTED = tuple(READERS)


def read_document(path: str) -> Doc:
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix not in READERS:
        raise ValueError(f"unsupported file type: {suffix or 'unknown'}")
    return READERS[suffix](path)


def fingerprint(doc: Doc) -> str:
    """Structural signature: heading texts + table shapes. Used to group format families."""
    parts = []
    for item in doc.items:
        if isinstance(item, Table):
            header = item.rows[0] if item.rows else []
            parts.append(
                "T" + str(len(header)) + "|" + "|".join(clean(c).lower()[:24] for c in header)
            )
        elif isinstance(item, Block) and heading(item.text, item.bold, item.size):
            text = clean(item.text).lower()
            if len(text) <= 80:
                parts.append("H|" + text)
    blob = "\n".join(parts[:200]) or "empty"
    return hashlib.sha1(blob.encode()).hexdigest()[:12]
