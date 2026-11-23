"""What is never indexed: title pages and slides, and blocks with a university (student) ID.

A title slide holds the course or lecture name and often the presenter's name and student number;
it answers no question and can leak personal data. A block anywhere that names a university ID is
dropped as well.

Title page: the first page or slide of a file with more than one page, when it is a title unit
(cb_shared: only a title, or a title and a short subtitle), or it is short (at most
TITLE_MAX_WORDS words), has a heading and no full sentence of SENTENCE_WORDS words or more.
A one-page file (a photo, a single sheet) is never skipped: it is the whole document.
"""
import re
from typing import List, Tuple

from cb_shared import TextUnit

TITLE_MAX_WORDS = 40
SENTENCE_WORDS = 12

# «الرقم الجامعي: 202012345», «رقم الطالب», "Student ID", "University No." ... and 9-digit numbers that
# start with a year (2000-2029), the usual form of a university number here.
UNIVERSITY_ID = re.compile(
    r"(?:ال)?رقم\s*(?:ال)?جامعي|رقم\s*(?:ال)?طالب|(?:student|university|matriculation)\s*(?:id|no\.?|number|#)"
    r"|(?<!\d)20[0-2]\d{6}(?!\d)", re.IGNORECASE)


def has_university_id(text: str) -> bool:
    return bool(UNIVERSITY_ID.search(text or ""))


def is_title_page(unit: TextUnit, unit_count: int) -> bool:
    if unit.number != 1 or unit_count <= 1:
        return False
    if unit.is_title_unit():
        return True
    if unit.words > TITLE_MAX_WORDS or not any(b.kind == "heading" for b in unit.blocks):
        return False
    sentences = re.split(r"(?<=[.!?؟])\s+", unit.text)
    return not any(len(s.split()) >= SENTENCE_WORDS and s.strip().endswith(tuple(".!?؟")) for s in sentences)


def filter_units(units: List[TextUnit]) -> Tuple[List[TextUnit], List[int], int]:
    """(units to index, skipped title pages, number of blocks dropped for a university ID)."""
    kept, skipped, dropped = [], [], 0
    count = len(units)
    for unit in units:
        if is_title_page(unit, count):
            skipped.append(unit.number)
            continue
        blocks = [b for b in unit.blocks if not has_university_id(b.text)]
        dropped += len(unit.blocks) - len(blocks)
        if len(blocks) != len(unit.blocks):
            unit = TextUnit(unit.number, unit.unit_type, blocks, unit.title, unit.source, dict(unit.meta))
        kept.append(unit)
    return kept, skipped, dropped
