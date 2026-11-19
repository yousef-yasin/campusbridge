"""References and footnotes: found on each page and turned into one block of kind "references".

Two shapes are recognised:
- a section with a title such as «المراجع», «المصادر», "References" or "Bibliography": the
  title and everything after it, up to the next heading of the same or a higher level;
- footnotes at the bottom of the page: the last blocks, each starting with (1), [1] or ¹, when
  the text above refers to that number («الأدوية(1)», "result [1]", "word¹", "word1").
  A numbered list at the end of a page with no such reference stays a list.

Speech does not read them by default: it says «في مراجع بآخر الصفحة.» instead
(to_speech_text(..., include_references=True) reads them).
"""
import re
from typing import List, Optional

from .lang import detect_language
from .model import Block, Page

TITLES = {"المراجع", "المصادر", "المصادر والمراجع", "المراجع والمصادر", "قائمة المراجع", "قائمة المصادر",
          "مراجع", "مصادر", "الهوامش", "الحواشي", "references", "reference", "bibliography",
          "works cited", "sources", "citations", "footnotes", "notes and references"}
_SUPERSCRIPT = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_MARK = re.compile(rf"^\s*(?:\((\d{{1,3}})\)|\[(\d{{1,3}})\]|([{_SUPERSCRIPT}]{{1,3}}))\s*\S")
_SPLIT = re.compile(rf"\s+(?=(?:\(\d{{1,3}}\)|\[\d{{1,3}}\]|[{_SUPERSCRIPT}]{{1,3}})\s*\S)")


def _number(match: re.Match) -> str:
    if match.group(3):
        return match.group(3).translate(str.maketrans(_SUPERSCRIPT, "0123456789"))
    return match.group(1) or match.group(2)


def is_title(block: Block) -> bool:
    if block.kind not in ("heading", "paragraph"):
        return False
    text = re.sub(r"[\s:：.]+$", "", " ".join(block.text.split())).strip().lower()
    return text in TITLES


def _lines(block: Block) -> List[str]:
    if block.kind == "list" and block.items:
        return [i for i in block.items if i.strip()]
    return [l for l in block.text.split("\n") if l.strip()]


def _refers_to(body: str, n: str) -> bool:
    sup = n.translate(str.maketrans("0123456789", _SUPERSCRIPT))
    return bool(re.search(rf"[\(\[]{n}[\)\]]|{re.escape(sup)}|(?<=[^\W\d_]){n}(?!\d)", body))


def _block(lines: List[str], like: Block) -> Block:
    text = "\n".join(lines)
    return Block("references", text, detect_language(text), like.unit, like.unit_type, like.sheet,
                 items=lines, source=like.source)


def mark_references(page: Page) -> Page:
    """Replace reference sections and bottom-of-page footnotes with "references" blocks (in place)."""
    blocks = page.blocks
    for i, block in enumerate(blocks):                           # 1. a titled section
        if not is_title(block):
            continue
        level = (block.level or 1) if block.kind == "heading" else 99
        end = i + 1
        while end < len(blocks) and not (blocks[end].kind == "heading" and (blocks[end].level or 1) <= level):
            end += 1
        entries = [l for b in blocks[i + 1:end] if b.kind != "image" for l in _lines(b)]
        if entries:
            ref = _block([" ".join(block.text.split())] + entries, block)
            ref.items = entries
            blocks[i:end] = [ref]
        break
    start = len(blocks)                                          # 2. footnotes at the bottom
    while start > 0 and blocks[start - 1].kind in ("paragraph", "list") and _MARK.match(blocks[start - 1].text):
        start -= 1
    if 0 < start < len(blocks):
        first: Optional[re.Match] = _MARK.match(blocks[start].text)
        body = " ".join(b.text for b in blocks[:start] if b.kind != "image")
        if first and _refers_to(body, _number(first)):
            entries = [e.strip() for b in blocks[start:] for l in _lines(b) for e in _SPLIT.split(l) if e.strip()]
            blocks[start:] = [_block(entries, blocks[start])]
    return page
