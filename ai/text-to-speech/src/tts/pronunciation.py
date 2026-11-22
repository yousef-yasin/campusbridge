"""Pronunciation dictionary: words as written -> how they should be spoken (with diacritics).

Applied to the text right before it goes to an engine (Gemini, Edge or Piper), so place names
and scientific terms are read correctly. Only the spoken text changes, never what is shown.

The JSON file has groups of entries ({"group": {"word": "spoken form"}}); keys starting with
"_" are notes. A word matches as a whole word, alone or with the prefixes و ف ب ك ل, and for
words starting with ال also the form with لل (للرصيفة). Text already written with diacritics
is left as it is.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .errors import ConfigError, PhraseError

_LETTER = "ء-يٱ-ۓً-ْٰ"     # Arabic letters and diacritics
_HARAKAT = re.compile("[ً-ْٰ]")


def strip_diacritics(text: str) -> str:
    return _HARAKAT.sub("", text)


class Pronunciations:
    def __init__(self, path, enabled: bool = True):
        self.path = Path(path)
        self.enabled = enabled
        self.groups: Dict[str, Dict[str, str]] = {}
        self._pattern: Optional[re.Pattern] = None
        self._forms: Dict[str, str] = {}
        self.load()

    # --- file --------------------------------------------------------------------------
    def load(self) -> None:
        if not self.path.is_file():
            self.groups = {}
        else:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise ConfigError(f"{self.path.name} is not valid JSON: {exc}") from None
            self.groups = {g: dict(v) for g, v in data.items() if not g.startswith("_") and isinstance(v, dict)}
            self._about = data.get("_about")
        self._build()

    def save(self) -> None:
        data = {"_about": getattr(self, "_about", None) or "word as written -> spoken form"}
        data.update(self.groups)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @property
    def entries(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for group in self.groups.values():
            out.update(group)
        return out

    def add(self, word: str, spoken: str, group: str = "custom") -> None:
        """Add or replace an entry and save the file."""
        word, spoken = " ".join(word.split()), " ".join(spoken.split())
        if not word or not spoken:
            raise PhraseError("word and spoken form must not be empty")
        if strip_diacritics(spoken).replace("ـ", "") != word:
            raise PhraseError(f"the spoken form '{spoken}' must be the same word '{word}' with diacritics")
        for entries in self.groups.values():
            entries.pop(word, None)
        self.groups.setdefault(group, {})[word] = spoken
        self.save()
        self._build()

    def remove(self, word: str) -> bool:
        found = False
        for entries in self.groups.values():
            found = entries.pop(word, None) is not None or found
        if found:
            self.save()
            self._build()
        return found

    # --- matching ----------------------------------------------------------------------
    def _build(self) -> None:
        forms: Dict[str, str] = {}
        for word, spoken in self.entries.items():
            forms[word] = spoken
            if word.startswith("ال"):                   # ل + ال = لل: للرصيفة
                forms["لل" + word[2:]] = "لل" + spoken[2:]
        self._forms = forms
        if not forms:
            self._pattern = None
            return
        alternatives = "|".join(re.escape(w).replace(r"\ ", r"\s+")
                                for w in sorted(forms, key=len, reverse=True))
        self._pattern = re.compile(rf"(?<![{_LETTER}])([وف]?[بكل]?)({alternatives})(?![{_LETTER}])")

    def apply(self, text: str) -> str:
        """The text with every known word replaced by its spoken form."""
        if not self.enabled or not text or self._pattern is None:
            return text

        def repl(match: re.Match) -> str:
            word = " ".join(match.group(2).split())
            return match.group(1) + self._forms.get(word, match.group(2))
        return self._pattern.sub(repl, text)

    def check(self) -> List[Tuple[str, str]]:
        """Entries whose spoken form is not the same word with diacritics (typos)."""
        return [(w, s) for w, s in self.entries.items() if strip_diacritics(s) != w]
