"""Text units -> chunks: one chunk per page or slide; a long page is split by blocks with a
small overlap. Every chunk keeps where it comes from, so an answer can name its source."""
import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from cb_shared import TextUnit

from .arabic import language_of

SOURCE_NAMES = {"text": "text", "image": "image description", "ocr": "OCR", "transcript": "transcript"}


@dataclass
class Chunk:
    id: str
    course: str
    file: str                         # file name (or a lecture id for a transcript)
    file_title: str
    unit: int                         # page / slide / sheet / transcript part number
    unit_type: str                    # page, slide, sheet, part
    title: str
    blocks: List[Dict[str, str]]      # [{"id", "kind", "text", "origin"}]
    part: int = 1                     # part of a long unit (1 when the unit is one chunk)
    parts: int = 1
    language: str = "en"              # ar, en, mixed
    sources: List[str] = field(default_factory=list)   # text, image, ocr, transcript
    meta: Dict[str, Any] = field(default_factory=dict)
    vector: Optional[List[float]] = None

    @property
    def text(self) -> str:
        return "\n".join(b["text"] for b in self.blocks)

    @property
    def block_ids(self) -> List[str]:
        return [b["id"] for b in self.blocks]

    @property
    def label(self) -> str:
        return f"{self.unit_type} {self.unit}" + (f" (part {self.part}/{self.parts})" if self.parts > 1 else "")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.embedding_text().encode("utf-8")).hexdigest()

    def embedding_text(self) -> str:
        """The text that is embedded (gemini-embedding-2 document format: 'title: ... | text: ...')."""
        title = self.title or self.file_title or "none"
        return f"title: {title} | text: {self.text}"

    def render(self, tag: str) -> str:
        """The chunk as the answer model sees it."""
        head = f"[{tag}] file: {self.file} | {self.unit_type} {self.unit}" + (f" | title: {self.title}" if self.title else "")
        lines = [f"({b['kind']}{', ' + SOURCE_NAMES.get(b.get('origin', 'text'), '') if b.get('origin', 'text') != 'text' else ''}) {b['text']}"
                 for b in self.blocks]
        return head + "\n" + "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Chunk":
        return cls(**data)


def _words(text: str) -> int:
    return len(text.split())


def _split(blocks: List[Dict[str, str]], part_words: int, overlap: int) -> List[List[Dict[str, str]]]:
    """Groups of whole blocks of about part_words words; each group starts with the last
    `overlap` blocks of the previous one. A single block longer than part_words stays whole."""
    groups: List[List[Dict[str, str]]] = []
    current: List[Dict[str, str]] = []
    count = 0
    fresh = 0                                     # blocks in current that are not overlap
    for block in blocks:
        n = _words(block["text"])
        if current and fresh and count + n > part_words:
            groups.append(current)
            current = current[-overlap:] if overlap else []
            count = sum(_words(b["text"]) for b in current)
            fresh = 0
        current.append(block)
        count += n
        fresh += 1
    if current and (fresh or not groups):
        groups.append(current)
    return groups


def chunk_units(units: Iterable[TextUnit], course: str, file: str, file_title: str = "",
                max_words: int = 350, part_words: int = 250, overlap_blocks: int = 1) -> List[Chunk]:
    chunks: List[Chunk] = []
    file_key = hashlib.sha256(f"{course}\n{file}".encode("utf-8")).hexdigest()[:12]
    for unit in units:
        blocks = [{"id": b.id, "kind": b.kind, "text": b.text, "origin": getattr(b, "origin", "text")}
                  for b in unit.blocks if b.text.strip()]
        if not blocks:
            continue
        total = sum(_words(b["text"]) for b in blocks)
        groups = [blocks] if total <= max_words else _split(blocks, part_words, overlap_blocks)
        for i, group in enumerate(groups, 1):
            text = "\n".join(b["text"] for b in group)
            sources = sorted({b["origin"] for b in group}, key=list(SOURCE_NAMES).index)
            chunks.append(Chunk(id=f"{file_key}-{unit.number}-{i}", course=course, file=file, file_title=file_title,
                                unit=unit.number, unit_type=unit.unit_type, title=unit.title, blocks=group,
                                part=i, parts=len(groups), language=language_of(text), sources=sources,
                                meta=dict(unit.meta)))
    return chunks
