"""Blocks -> plain text for the text-to-speech module, one entry per page/slide/sheet."""
from dataclasses import dataclass
from typing import Iterable, List, Optional, Union

import re

from .explain import (AUTO_LABEL, HANDWRITTEN_LABEL, MANUAL_LABEL, NEEDS_OCR, NO_DESCRIPTION, OCR_INTRO,
                      OCR_INTRO_LOCAL, REFERENCES_LABEL, REFERENCES_NOTE, REVIEW_NO_TEXT, REVIEW_NUMBERS,
                      UNCLEAR_WORD, explain_language)
from .lang import detect_language
from .model import Block, Page
from .numbers import has_number
from .tables import table_text

_UNCLEAR = "[unclear]"                  # same marker as ocr.UNCLEAR

_END = tuple(".!?؟…:؛")
_SENTENCES = re.compile(r"(?:[^.!?؟؛\n]|(?<=\d)\.(?=\d))+(?:[.!?؟؛]+|$)")   # 95.4 is not a sentence end


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


def _image_speech(image: dict, detailed: bool) -> str:
    status = image.get("status")
    mode = image.get("language") or "mixed"
    if status == "decorative":
        return ""
    if status == "undescribed":
        return NO_DESCRIPTION.get(mode, NO_DESCRIPTION["mixed"])
    desc = ((image.get("details") if detailed else None) or image.get("description") or "").strip()
    if not desc:
        return ""                                       # not processed by the describer
    unverified = (image.get("unverified_numbers") or []) if status == "needs_review" else []
    if unverified:                                      # drop the sentences with unconfirmed numbers
        desc = " ".join(s for s in _SENTENCES.findall(desc) if s.strip() and not has_number(s, unverified))
    if status == "manual":
        label = MANUAL_LABEL.get(mode, MANUAL_LABEL["mixed"])
    elif status in ("described", "needs_review"):
        label = AUTO_LABEL.get(mode, AUTO_LABEL["mixed"])
    else:                                               # description set by other code
        label = "صورة:" if detect_language(desc) in ("ar", "mixed") else "Image:"
    parts = [_sentence(f"{label} {desc}")] if desc else []
    text = (image.get("text") or "").strip()
    if image.get("category") == "table" and image.get("table"):
        parts += [_sentence(l) for l in table_text(image["table"]).split("\n") if l.strip()]
    elif image.get("category") in ("text", "screenshot") and text and status != "manual":
        parts.append(text)
    elif unverified:                                    # numbers from the image, not the model
        parts.append(f"{REVIEW_NUMBERS.get(mode, REVIEW_NUMBERS['mixed'])} {text}" if text
                     else REVIEW_NO_TEXT.get(mode, REVIEW_NO_TEXT["mixed"]))
    return "\n".join(parts)


def block_speech(block: Block, include_notes: bool = True, detailed_images: bool = False,
                 mode: Optional[str] = None, include_references: bool = False) -> str:
    """How one block is read aloud ('' when it is skipped).

    Text read by OCR has its unreadable words marked [unclear]: they are said «كلمة غير واضحة»
    ("unclear word" in en mode). A handwritten block is said «ملاحظة بخط اليد: ...».
    References are announced «في مراجع بآخر الصفحة.», or read with include_references=True.
    """
    if block.kind == "references":
        mode = mode or explain_language()
        if not include_references:
            return REFERENCES_NOTE[mode]
        entries = block.items or [l for l in block.text.split("\n") if l.strip()]
        text = "\n".join([REFERENCES_LABEL[mode]] + [_sentence(e) for e in entries])
    elif block.kind == "handwritten":
        label = HANDWRITTEN_LABEL[mode or explain_language()]
        text = _sentence(f"{label} {' '.join(block.text.split())}")
    else:
        text = _block_speech(block, include_notes, detailed_images)
    if block.source == "ocr" and _UNCLEAR in text:
        phrase = UNCLEAR_WORD[mode or explain_language()]
        text = text.replace(_UNCLEAR, f"({phrase})")
    return text


def ocr_lead(page: Page) -> Optional[str]:
    """What speech says first on a page that needed OCR (None for other pages)."""
    ocr = page.ocr or {}
    mode = ocr.get("language") or explain_language()
    if any(b.source == "ocr" for b in page.blocks):
        return (OCR_INTRO_LOCAL if ocr.get("engine") == "tesseract" else OCR_INTRO)[mode]
    if page.needs_ocr and ocr.get("status") != "no_text":
        return NEEDS_OCR[mode]
    return None


def _block_speech(block: Block, include_notes: bool, detailed_images: bool) -> str:
    if block.kind == "image":
        return _image_speech(block.image or {}, detailed_images)
    if block.kind == "chart":
        return "\n".join(_sentence(l) for l in block.text.split("\n") if l.strip())
    if block.kind == "notes":
        if not include_notes:
            return ""
        prefix = "ملاحظات المحاضر: " if _arabic(block) else "Speaker notes: "
        return prefix + "\n".join(_sentence(l) for l in block.text.split("\n") if l.strip())
    if block.kind == "table" and block.table:
        rows = len(block.table["rows"])
        total = block.table.get("total_rows", rows)
        if not total:                                   # header only: no "table with 0 rows"
            return "\n".join(_sentence(l) for l in block.text.split("\n") if l.strip())
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
                   include_notes: bool = True, detailed_images: bool = False,
                   include_references: bool = False) -> List[SpeechUnit]:
    """Text ready for text-to-speech, page by page.

    source: a Page, pages (document.pages()) or blocks. Blocks are separated by blank lines,
    so the TTS module splits long pages at block boundaries. Images without a description
    are skipped; headings and list items get a final period so the voice pauses.
    Described images are read as «وصف تلقائي: <short description>» (detailed_images=True reads
    the detailed description); a manual description is read as «صورة: ...»; decorative images
    are skipped; images the describer could not handle are announced as «صورة بدون وصف».
    When a description has numbers that are not in the image (status needs_review), its
    sentences with those numbers are dropped and the text read from the image follows
    «الأرقام كما وردت في الصورة:».
    A page whose text was read by OCR starts with «نص مستخرج تلقائياً من صورة الصفحة.»; a scanned
    page whose text was not read yet says «صفحة ممسوحة لم يُستخرج نصها بعد، وتحتاج OCR.».
    References and footnotes are not read: «في مراجع بآخر الصفحة.» (include_references=True reads them).
    """
    if isinstance(source, Page):
        source = [source]
    groups = {}
    for item in source:
        blocks = item.blocks if isinstance(item, Page) else [item]
        mode = None
        if isinstance(item, Page):
            lead = ocr_lead(item)
            mode = (item.ocr or {}).get("language")
            if lead:
                groups.setdefault((item.unit, item.unit_type, item.sheet), []).append(lead)
        for block in blocks:
            key = (block.unit, block.unit_type, block.sheet)
            groups.setdefault(key, [])
            text = block_speech(block, include_notes, detailed_images, mode, include_references)
            if text:
                groups[key].append(text)
        if isinstance(item, Page):
            groups.setdefault((item.unit, item.unit_type, item.sheet), [])
    return [SpeechUnit(unit, unit_type, "\n\n".join(parts), sheet)
            for (unit, unit_type, sheet), parts in groups.items()]
