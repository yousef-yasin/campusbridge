"""The generic input of the AI text features: numbered text units made of numbered blocks.

A unit is a page or slide of a document (from document-reader), or a time window of a lecture
transcript (from speech-to-text, later). Every block has an id ("b1", "b2", ...) so results can
point to where a fact came from.
"""
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

_SENTENCE_END = tuple(".!?؟:…")


@dataclass
class UnitBlock:
    id: str                      # "b1", "b2", ... (unique inside the unit)
    kind: str                    # heading, paragraph, list, table, image, chart, notes, handwritten, speech
    text: str
    origin: str = "text"         # "text", "image" (an image description) or "ocr" (read from a page image)


@dataclass
class TextUnit:
    number: int                  # page / slide number, or the transcript part number
    unit_type: str               # "page", "slide", "sheet", "part"
    blocks: List[UnitBlock] = field(default_factory=list)
    title: str = ""
    source: str = "document"     # "document" or "transcript"
    meta: Dict[str, Any] = field(default_factory=dict)   # e.g. {"start": 0.0, "end": 300.0}

    @property
    def label(self) -> str:
        return f"{self.unit_type} {self.number}"

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.text)

    @property
    def words(self) -> int:
        return len(re.findall(r"\w+", self.text))

    def block(self, block_id: str) -> Optional[UnitBlock]:
        return next((b for b in self.blocks if b.id == block_id), None)

    def digest(self) -> str:
        """Hash of the content (cache key): changes when any block changes."""
        data = json.dumps([[b.kind, b.text] for b in self.blocks], ensure_ascii=False)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def render(self) -> str:
        """The unit as the models see it: one line per block, '[b3] (list) ...'."""
        lines = [f"Title: {self.title}" if self.title else "Title: (none)"]
        lines += [f"[{b.id}] ({b.kind}) {b.text}" for b in self.blocks]
        return "\n".join(lines)

    def is_title_unit(self) -> bool:
        """The first page/slide with only a title, or a title and a short subtitle."""
        if self.number != 1 or self.source != "document":
            return False
        texts = [b for b in self.blocks if b.kind not in ("image",)]
        if not texts or len(texts) > 2 or any(b.kind not in ("heading", "paragraph") for b in texts):
            return False
        return any(b.kind == "heading" for b in texts) and all(
            len(b.text) <= 80 and not b.text.strip().endswith(_SENTENCE_END) for b in texts)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _image_text(image: Dict[str, Any]) -> str:
    """An image as text, only when phase 2 described it (decorative and undescribed: nothing)."""
    if image.get("status") not in ("described", "manual", "needs_review"):
        return ""
    parts = [f"Image: {image.get('description', '').strip()}"]
    if (image.get("text") or "").strip():
        parts.append(f"Text in the image: {image['text'].strip()}")
    return " ".join(p for p in parts if p.strip(": "))


def from_pages(pages: Iterable[Any]) -> List[TextUnit]:
    """document-reader pages -> units (text, image descriptions, chart data, notes and OCR text).

    References and footnotes are left out (they are not lecture content), and so are images
    without a description.
    """
    units = []
    for page in pages:
        blocks: List[UnitBlock] = []
        title = ""
        for block in page.blocks:
            kind = block.kind
            if kind == "references":
                continue
            if kind == "image":
                text = _image_text(block.image or {})
            elif kind == "list":
                text = "\n".join(block.items or block.text.split("\n"))
            else:
                text = block.text
            text = text.strip()
            if not text:
                continue
            if kind == "heading" and not title:
                title = " ".join(text.split())
            origin = "image" if kind == "image" else ("ocr" if getattr(block, "source", None) == "ocr" else "text")
            blocks.append(UnitBlock(f"b{len(blocks) + 1}", kind, text, origin))
        units.append(TextUnit(page.unit, page.unit_type, blocks, title,
                              meta={"sheet": page.sheet} if getattr(page, "sheet", None) else {}))
    return units


def from_transcript(segments: Iterable[Dict[str, Any]], seconds_per_unit: float = 300.0,
                    title: str = "") -> List[TextUnit]:
    """speech-to-text segments [{"start", "end", "text"}] -> units of about seconds_per_unit each."""
    units: List[TextUnit] = []
    current: Optional[TextUnit] = None
    for seg in segments:
        text = " ".join(str(seg.get("text", "")).split())
        if not text:
            continue
        start = float(seg.get("start", 0.0))
        if current is None or start - current.meta["start"] >= seconds_per_unit:
            current = TextUnit(len(units) + 1, "part", [], title, source="transcript",
                               meta={"start": start, "end": start})
            units.append(current)
        current.blocks.append(UnitBlock(f"b{len(current.blocks) + 1}", "speech", text, "transcript"))
        current.meta["end"] = float(seg.get("end", start))
    return units
