"""Text cleanup, Arabic/English detection, and repair of visually ordered Arabic."""
import re
import unicodedata
from typing import Optional

_AR = re.compile("[ء-يٮ-ۓۺ-ۿﭐ-﷿ﹰ-ﻼ]")
_LATIN = re.compile("[A-Za-zÀ-ɏ]")
_PRESENTATION = re.compile("[ﬀ-ﬆﭐ-﷿ﹰ-ﻼ]")
# controls (except tab/newline), soft hyphen, bidi marks and isolates, BOM, private use (bullet glyphs)
_DROP = re.compile("[\x00-\x08\x0B-\x1F\x7F­​-‏‪-‮⁦-⁩﻿-]")
_SPACES = re.compile(r"[^\S\n]+")
# PDFs often put a space before a shadda/tanween drawn as a separate glyph: "ومهي ّأة"
_SPACE_BEFORE_MARK = re.compile(r"[^\S\n]+(?=[ً-ْٰ])")
_MARKS = re.compile("[ً-ْٰ]")
_AR_PLAIN = re.compile("[ء-ي]+")
_MIRROR = str.maketrans("()[]{}<>", ")(][}{><")
_LTR_RUN = re.compile(r"[A-Za-z0-9À-ɏ][A-Za-z0-9À-ɏ.,:/%+\-_' ]*[A-Za-z0-9À-ɏ%]|[A-Za-z0-9]")

MIXED_SHARE = 0.10      # minority script >= 10% of the words ...
MIXED_WORDS = 3         # ... or at least 3 words -> "mixed"


def _form(ch: str) -> str:
    name = unicodedata.name(ch, "")
    for form in ("INITIAL", "MEDIAL", "FINAL", "ISOLATED"):
        if f"{form} FORM" in name:
            return form
    return ""


def is_visual_order(line: str) -> bool:
    """True when Arabic in this line is stored right-to-left as drawn (reversed).

    Only detectable when the PDF keeps Arabic presentation forms: in logical order a word
    starts with an initial (or isolated) form; reversed, it starts with a final form.
    """
    reversed_words = logical_words = 0
    for word in re.findall("[ﭐ-﷿ﹰ-ﻼ]{2,}", line):
        first, last = _form(word[0]), _form(word[-1])
        if first == "FINAL" or last == "INITIAL":
            reversed_words += 1
        elif first == "INITIAL" or last == "FINAL":
            logical_words += 1
    return reversed_words > logical_words


def fix_visual_order(line: str) -> str:
    """Reverse a visually ordered line, keeping Latin words and numbers left-to-right."""
    if not is_visual_order(line):
        return line
    flipped = line[::-1].translate(_MIRROR)
    return _LTR_RUN.sub(lambda m: m.group(0)[::-1], flipped)


def clean_text(text: str) -> str:
    """Presentation forms -> letters, drop invisible characters, tidy spaces."""
    if not text:
        return ""
    text = _PRESENTATION.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), text)
    text = _DROP.sub("", text).replace("ـ", "")          # tatweel is decoration
    text = _SPACES.sub(" ", text)
    text = _SPACE_BEFORE_MARK.sub("", text)                    # a word never starts with a mark
    return "\n".join(line.strip() for line in text.split("\n")).strip()


_LEADING_MARKS = re.compile("^([ً-ْٰ]+)")


def fix_leading_marks(text: str) -> str:
    """A diacritic at the start of a paragraph belongs to its last word.

    Some PDFs store the tanween of the last word of a right-to-left line as a separate glyph,
    and text extraction puts it first: 'ًيحوّل ... يوميا' -> 'يحوّل ... يومياً'.
    """
    match = _LEADING_MARKS.match(text or "")
    if not match or not has_arabic(text):
        return text
    return text[match.end():].rstrip() + match.group(1)


def looks_reversed(text: str) -> bool:
    """Arabic stored letter by letter in reverse, without presentation forms to repair it.

    Reversed words start with ة or ى (impossible in Arabic) or end with 'لا' (a reversed 'ال');
    normal text has many words starting with 'ال' or ending with ة/ى.
    """
    words = [w for w in _AR_PLAIN.findall(_MARKS.sub("", text or "")) if len(w) >= 3]
    reversed_words = sum(w[0] in "ةى" or (len(w) >= 4 and w.endswith("لا")) for w in words)
    logical_words = sum(w.startswith("ال") or w[-1] in "ةى" for w in words)
    return reversed_words >= 3 and reversed_words > logical_words


def word_counts(text: str):
    ar = en = 0
    for word in (text or "").split():
        if _AR.search(word):
            ar += 1
        elif _LATIN.search(word):
            en += 1
    return ar, en


def detect_language(text: str) -> Optional[str]:
    """'ar', 'en' or 'mixed' by counting words of each script; None when there are no letters."""
    ar, en = word_counts(text)
    if not ar and not en:
        return None
    minority = min(ar, en)
    if minority and (minority / (ar + en) >= MIXED_SHARE or minority >= MIXED_WORDS):
        return "mixed"
    return "ar" if ar > en else "en"


def is_rtl(text: str) -> bool:
    """Page/slide direction: more Arabic than Latin words."""
    ar, en = word_counts(text)
    return ar > en


def has_arabic(text: str) -> bool:
    return bool(_AR.search(text or ""))
