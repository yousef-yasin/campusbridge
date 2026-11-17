"""Blocks -> plain text for the text-to-speech module, one entry per page/slide/sheet."""
from dataclasses import dataclass
from typing import Iterable, List, Optional, Union

from .lang import detect_language
from .model import Block, Page

_END = tuple(".!?؟…:؛")


@dataclass
class SpeechUnit:
    unit: int
    unit_type: str
    text: str
    sheet: Optional[str] = None


def _sentence(text: str) -> str:
    text = " ".join(text.split())
    return text if not text or text.endswith(_END) else f"{text}."


def _arabic(block: Block) -> bool:
    return block.lang in ("ar", "mixed")


def block_speech(block: Block, include_notes: bool = True) -> str:
    """How one block is read aloud ('' when it is skipped)."""
    if block.kind == "image":
        desc = (block.image or {}).get("description", "").strip()
        if not desc:
            return ""                                   # filled in by phase 2
        prefix = "صورة: " if detect_language(desc) in ("ar", "mixed") else "Image: "
        return _sentence(prefix + desc)
    if block.kind == "notes":
        if not include_notes:
            return ""
        prefix = "ملاحظات المحاضر: " if _arabic(block) else "Speaker notes: "
        return prefix + "\n".join(_sentence(l) for l in block.text.split("\n") if l.strip())
    if block.kind == "table" and block.table:
        rows = len(block.table["rows"])
        total = block.table.get("total_rows", rows)
        if _arabic(block):
            intro = f"جدول، عدد صفوفه {total}." if total == rows else \
                f"جدول، عدد صفوفه {total}، وهذه أول {rows} منها:"
        else:
            plural = "s" * (total != 1)
            intro = f"Table with {total} row{plural}." if total == rows else \
                f"Table with {total} row{plural}, the first {rows}:"
        lines = [_sentence(l) for l in block.text.split("\n") if l.strip()]
        return "\n".join([intro] + lines)
    if block.kind == "list":
        return "\n".join(_sentence(i) for i in (block.items or block.text.split("\n")) if i.strip())
    return _sentence(block.text) if block.kind == "heading" else " ".join(block.text.split())


def to_speech_text(source: Union[Page, Iterable[Page], Iterable[Block]],
                   include_notes: bool = True) -> List[SpeechUnit]:
    """Text ready for text-to-speech, page by page.

    source: a Page, pages (document.pages()) or blocks. Blocks are separated by blank lines,
    so the TTS module splits long pages at block boundaries. Images without a description
    are skipped; headings and list items get a final period so the voice pauses.
    """
    if isinstance(source, Page):
        source = [source]
    groups = {}
    for item in source:
        blocks = item.blocks if isinstance(item, Page) else [item]
        for block in blocks:
            key = (block.unit, block.unit_type, block.sheet)
            groups.setdefault(key, [])
            text = block_speech(block, include_notes)
            if text:
                groups[key].append(text)
        if isinstance(item, Page):
            groups.setdefault((item.unit, item.unit_type, item.sheet), [])
    return [SpeechUnit(unit, unit_type, "\n\n".join(parts), sheet)
            for (unit, unit_type, sheet), parts in groups.items()]
