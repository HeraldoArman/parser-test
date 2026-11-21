"""Document model shared by all readers: an ordered list of blocks and tables."""
from dataclasses import dataclass, field
from typing import Any, Optional, Union


@dataclass
class Block:
    text: str
    page: Optional[int] = None
    order: int = 0
    bold: bool = False
    size: float = 0.0

    def to_dict(self) -> dict:
        return {"type": "block", "text": self.text, "page": self.page,
                "order": self.order, "bold": self.bold, "size": self.size}


@dataclass
class Table:
    rows: list[list[str]]
    page: Optional[int] = None
    order: int = 0
    ocr: bool = False

    def to_dict(self) -> dict:
        return {"type": "table", "rows": self.rows, "page": self.page,
                "order": self.order, "ocr": self.ocr}


Item = Union[Block, Table]


@dataclass
class Doc:
    items: list[Item] = field(default_factory=list)
    page_count: int = 0
    text_length: int = 0
    suffix: str = ""
    ocr_pages: int = 0
    ocr_limited: bool = False

    @property
    def scanned(self) -> bool:
        return self.suffix == "pdf" and self.page_count > 0 and self.text_length < 100

    def text(self) -> str:
        return "\n".join(i.text for i in self.items if isinstance(i, Block))

    def to_json(self) -> list[dict]:
        return [i.to_dict() for i in self.items]


def items_from_json(data: Any) -> list[dict]:
    return data or []
