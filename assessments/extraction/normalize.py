"""Text hygiene and heading heuristics. No document-specific rules live here."""
import re
import unicodedata

BULLET_CHARS = "\u2022\u25cf\u25aa\u25cb\u25e6\u2023\u2043\u00b7\u2219*-\u2013\u2014>"
_BULLET_CLASS = re.escape(BULLET_CHARS)

_NUMBERING = re.compile(r"^[\s" + _BULLET_CLASS + r"]*(?:\d+[.)]?|[a-zA-Z][.)])\s+(?=\S)")
_BULLETS = re.compile(r"^[\s" + _BULLET_CLASS + r"]+")


def clean(value: str) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = re.sub(r"[\ue000-\uf8ff]", "", text)  # symbol-font bullets (Wingdings and friends)
    return re.sub(r"\s+", " ", text).strip()


def strip_leading(text: str) -> str:
    text = _NUMBERING.sub("", text)
    return _BULLETS.sub("", text).strip()


def strip_trailing_punct(text: str) -> str:
    return re.sub(r"[\s:;,\u2013\u2014\-\.]+$", "", text).strip()


def heading(text: str, bold: bool = False, size: float = 0.0) -> bool:
    """Cheap heading test: short, label-like, and either numbered, bold, uppercase or ending in ':'."""
    t = clean(text)
    if not t or len(t) > 130:
        return False
    words = t.split()
    if len(words) > 14:
        return False
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return False
    upper = sum(c.isupper() for c in letters) / len(letters)
    if re.match(r"^[A-Z]\.\s?\S", t):
        return True
    if re.match(r"^\d+(\.\d+){0,3}\.?\s+[A-Z]", t):
        return True
    if t.endswith(":") and len(words) <= 10:
        return True
    if bold and len(words) <= 12:
        return True
    if upper > 0.85 and len(words) <= 10:
        return True
    return False


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", clean(text).lower())}
