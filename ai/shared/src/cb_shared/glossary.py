"""Shared glossary: English technical term -> its correct Arabic meaning.

The file uses the speech-to-text glossary format (schema 1: course, version, sha256, terms with
term/kind/aliases), so one course glossary can serve both modules: speech-to-text reads the
"aliases" (how a term sounds in Arabic script) and ignores the meanings; this module reads
"meaning_ar" (and "accepted_ar", other correct wordings) and ignores the aliases. The sha256 is
computed the same way (canonical JSON without the sha256 key), so a published version cannot
be edited silently.

Use:
- prompt_rules(text, mode): for "ar" and "mixed", the meanings of the terms found in the text,
  for the model's instructions;
- wrong_meanings(texts): Arabic written next to a glossary term, «term (meaning)» or
  «meaning (term)», that does not match the glossary.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "glossary" / "terms.json"
SCHEMA = 1

_HARAKAT = re.compile(r"[ً-ْٰـ]")
_ARABIC_WORDS = re.compile(r"[ء-ي]+")
_PREFIXES = ("وال", "بال", "فال", "كال", "لل", "ال")


class GlossaryError(ValueError):
    """The glossary file is missing, malformed or was modified without a new version."""


def canonical_sha256(data: dict) -> str:
    """Same rule as speech-to-text's glossary.compute_sha256."""
    body = {k: v for k, v in data.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _norm_words(text: str) -> List[str]:
    """Arabic words without diacritics, with أ/إ/آ -> ا, ة -> ه, ى -> ي and no leading ال."""
    text = _HARAKAT.sub("", text or "")
    text = re.sub("[أإآ]", "ا", text).replace("ة", "ه").replace("ى", "ي")
    words = []
    for word in _ARABIC_WORDS.findall(text):
        for prefix in _PREFIXES:
            if word.startswith(prefix) and len(word) - len(prefix) >= 2:
                word = word[len(prefix):]
                break
        words.append(word)
    return words


def _contains(haystack: List[str], needle: List[str]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


@dataclass
class Entry:
    term: str
    meaning: str
    accepted: List[str] = field(default_factory=list)
    domain: str = ""

    def matches(self, arabic: str) -> bool:
        """True when the Arabic text contains the glossary meaning or an accepted wording."""
        words = _norm_words(arabic)
        return any(_contains(words, _norm_words(m)) for m in [self.meaning] + self.accepted)


class Glossary:
    def __init__(self, data: dict, path: Optional[Path] = None):
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise GlossaryError(f"unsupported glossary schema {data.get('schema') if isinstance(data, dict) else data!r}")
        if data.get("sha256") != canonical_sha256(data):
            raise GlossaryError(f"glossary {data.get('course')} v{data.get('version')} failed its integrity check "
                                f"(content was modified); publish a new version instead of editing it")
        self.course, self.version, self.sha256, self.path = data.get("course"), data.get("version"), data["sha256"], path
        self.entries: Dict[str, Entry] = {}
        for raw in data.get("terms") or []:
            if raw.get("meaning_ar"):
                entry = Entry(raw["term"], raw["meaning_ar"], list(raw.get("accepted_ar") or []), raw.get("domain", ""))
                self.entries[entry.term.lower()] = entry
        names = sorted(self.entries, key=len, reverse=True)           # longest first: one term per place
        self._terms = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z])",
                                 re.IGNORECASE) if names else None

    @property
    def info(self) -> dict:
        return {"course": self.course, "version": self.version, "sha256": self.sha256}

    def find(self, text: str) -> List[Entry]:
        """Glossary terms that appear in the text (English), in order of first appearance."""
        found: Dict[str, Entry] = {}
        for match in (self._terms.finditer(text or "") if self._terms else []):
            found.setdefault(match.group(1).lower(), self.entries[match.group(1).lower()])
        return list(found.values())

    def prompt_rules(self, text: str, mode: str) -> str:
        """Instruction lines with the meanings of the terms found in the text ('' in en mode)."""
        if mode == "en":
            return ""
        entries = self.find(text)
        if not entries:
            return ""
        lines = "\n".join(f"- {e.term} = {e.meaning}" for e in entries)
        return ("Glossary: when you give the Arabic meaning of one of these terms, use exactly this "
                "Arabic meaning (not another translation):\n" + lines)

    def wrong_meanings(self, texts: Iterable[str]) -> List[str]:
        """«term (Arabic)» or «Arabic (term)» where the Arabic does not match the glossary."""
        problems: List[str] = []
        if not self._terms:
            return problems
        for text in texts:
            text = text or ""
            for match in self._terms.finditer(text):
                entry = self.entries[match.group(1).lower()]
                after = re.match(r"\s*\(([^()]*)\)", text[match.end():])
                before = re.search(r"([^().،,:؛;]*?)\s*\(\s*$", text[:match.start()])
                closes = re.match(r"\s*\)", text[match.end():])
                arabic = after.group(1) if after else (before.group(1) if before and closes else None)
                if arabic is None or not _norm_words(arabic):
                    continue
                if not entry.matches(arabic):
                    problem = f"'{entry.term}' explained as «{arabic.strip()}», glossary: «{entry.meaning}»"
                    if problem not in problems:
                        problems.append(problem)
        return problems


_DEFAULT: Optional[Glossary] = None


def load_glossary(path=None) -> Glossary:
    """The glossary at path (default: ai/shared/glossary/terms.json, CB_GLOSSARY_FILE)."""
    global _DEFAULT
    import os
    path = Path(path or os.environ.get("CB_GLOSSARY_FILE") or DEFAULT_PATH)
    if path == DEFAULT_PATH and _DEFAULT is not None:
        return _DEFAULT
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GlossaryError(f"glossary not found: {path}") from None
    except (OSError, ValueError) as exc:
        raise GlossaryError(f"cannot read glossary {path}: {exc}") from None
    glossary = Glossary(data, path)
    if path == DEFAULT_PATH:
        _DEFAULT = glossary
    return glossary
