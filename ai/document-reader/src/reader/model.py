"""The unified structure every format is converted to."""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

KINDS = ("heading", "paragraph", "list", "table", "image", "chart", "notes")


@dataclass
class Block:
    """One piece of content, in reading order.

    unit: 1-based page (pdf, docx), slide (pptx) or sheet index (xlsx).
    sheet: sheet name (xlsx only).
    lang: "ar", "en", "mixed", or None when the text has no letters.
    """
    kind: str
    text: str
    lang: Optional[str]
    unit: int
    unit_type: str = "page"                 # page / slide / sheet
    sheet: Optional[str] = None
    level: Optional[int] = None             # heading level (1 = top)
    items: Optional[List[str]] = None       # list items
    table: Optional[Dict[str, Any]] = None  # {"columns": [...], "rows": [[...]], "total_rows": n}
    image: Optional[Dict[str, Any]] = None  # {"path", "sha256", "ext", "width", "height", "description", ...}
    chart: Optional[Dict[str, Any]] = None  # native chart: {"type", "title", "categories", "series", ...}

    @property
    def location(self) -> Dict[str, Any]:
        return {"sheet": self.sheet} if self.unit_type == "sheet" else {self.unit_type: self.unit}

    def to_dict(self) -> Dict[str, Any]:
        data = {k: v for k, v in asdict(self).items() if v is not None}
        data.update(self.location)
        return data


@dataclass
class Page:
    """One page, slide or sheet."""
    unit: int
    unit_type: str
    blocks: List[Block] = field(default_factory=list)
    sheet: Optional[str] = None
    needs_ocr: bool = False                 # PDF page with images but no text layer
    warnings: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"sheet {self.sheet}" if self.unit_type == "sheet" else f"{self.unit_type} {self.unit}"

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks if b.text)

    def to_dict(self) -> Dict[str, Any]:
        data = {"unit": self.unit, "unit_type": self.unit_type, "needs_ocr": self.needs_ocr,
                "blocks": [b.to_dict() for b in self.blocks]}
        if self.sheet is not None:
            data["sheet"] = self.sheet
        if self.warnings:
            data["warnings"] = self.warnings
        return data


@dataclass
class OutlineEntry:
    """A topic and where it starts."""
    title: str
    unit: int
    level: int = 1
    sheet: Optional[str] = None


@dataclass
class SheetInfo:
    name: str
    index: int                  # 1-based
    columns: List[str]
    row_count: int              # data rows, header excluded
    header_row: int             # 1-based row number of the header
    rtl: bool = False
    hidden: bool = False
    title: Optional[str] = None        # text above the header (a title row), if any
    approximate: bool = False          # row_count estimated from the sheet size (very large sheet)


@dataclass
class DocumentInfo:
    title: str
    file_type: str              # docx / pdf / pptx / xlsx
    unit_type: str              # page / slide / sheet
    unit_count: int
    image_count: int
    table_count: int
    language: Optional[str]
    outline: List[OutlineEntry] = field(default_factory=list)
    needs_ocr: bool = False
    ocr_pages: List[int] = field(default_factory=list)
    sheets: List[SheetInfo] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    chart_count: int = 0        # native charts read from the file (not pictures of charts)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if not self.sheets:
            data.pop("sheets")
        return data
