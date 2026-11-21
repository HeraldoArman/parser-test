"""Weight token parsing: '25%', '7,5', '2 x @7.5%', '10-15', '5% (bonus)'."""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .normalize import clean

_RANGE = re.compile(r"\d+(?:[.,]\d+)?\s*[-\u2013\u2014]\s*\d+(?:[.,]\d+)?")
_MULT = re.compile(r"(\d+)\s*[x\u00d7]\s*@?\s*(\d+(?:[.,]\d+)?)")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_PERCENT = re.compile(r"%")


@dataclass
class Weight:
    value: Decimal | None
    raw: str
    bonus: bool = False
    is_range: bool = False
    formula: str = ""


def parse_weight(raw) -> Weight | None:
    text = clean(raw)
    if not text or not _NUM.search(text):
        return None
    bonus = "bonus" in text.lower()
    mult = _MULT.search(text)
    if mult:
        try:
            value = Decimal(mult.group(1)) * Decimal(mult.group(2).replace(",", "."))
        except InvalidOperation:
            return None
        return Weight(value, text, bonus, False, mult.group(0))
    if _RANGE.search(text):
        return Weight(None, text, bonus, True)
    numbers = _NUM.findall(text.replace(" ", ""))
    if not numbers:
        return None
    try:
        return Weight(Decimal(numbers[-1].replace(",", ".")), text, bonus)
    except InvalidOperation:
        return None


def is_percent(text: str) -> bool:
    return bool(_PERCENT.search(clean(text)))


def as_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
