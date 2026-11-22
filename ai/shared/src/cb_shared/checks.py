"""Checks after generation: the model may only use what is in the source text.

- Numbers: every number in the generated text must appear in the source. This is
  document-reader's numbers.py (digits and Arabic/English number words, compared by value),
  used here rather than copied.
- English words: in "ar" and "mixed" modes English appears only as technical terms, so every
  English word must appear in the source. In "en" mode only the terms are checked (the
  explanation itself is English prose).
- Block ids: a point or an answer must name a block that exists.
"""
import re
from typing import Iterable, List

from .paths import use_module

_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z\-']+")
_MIN_LEN = 3                 # "of", "is", "x" are not checked


_numbers = None


def _numbers_module():
    """document-reader's numbers.py, loaded from its file (it only needs the standard library),
    so this check works without document-reader's other dependencies."""
    global _numbers
    if _numbers is None:
        import importlib.util
        path = use_module("document-reader") / "reader" / "numbers.py"
        spec = importlib.util.spec_from_file_location("cb_shared._reader_numbers", path)
        _numbers = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_numbers)
    return _numbers


def unverified_numbers(generated: Iterable[str], sources: Iterable[str]) -> List[str]:
    return _numbers_module().unverified_numbers(list(generated), list(sources))


def _words(text: str) -> set:
    return {w.lower().strip("-'") for w in _LATIN_WORD.findall(text or "")}


def missing_english(generated: Iterable[str], source: str) -> List[str]:
    """English words in the generated text that the source never uses."""
    known = _words(source)
    missing: List[str] = []
    for text in generated:
        for word in _LATIN_WORD.findall(text or ""):
            w = word.lower().strip("-'")
            if len(w) >= _MIN_LEN and w not in known and w not in missing:
                # plural / possessive forms of a source word are fine ("means" for "mean")
                if not any(w.rstrip("s") == k.rstrip("s") for k in known):
                    missing.append(w)
    return missing
