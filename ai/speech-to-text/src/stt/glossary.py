"""Approved course glossary: loading, validation, integrity hash and alias index.

Only aliases with status "approved" are used. The file's "sha256" must equal the hash of its
canonical content, so a published version cannot be edited silently; transcripts record
{course, version, sha256} of the glossary that produced them.
"""
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .errors import GlossaryError

SCHEMA = 1
KINDS = {"word", "short", "phrase", "acronym_letters", "acronym_word"}
STATUSES = {"proposed", "approved", "rejected"}
SHORT_MAX = 3            # alias keys of <= 3 letters must be kind "short" (or an acronym)
FUZZY_MIN = 6            # only "word" aliases with >= 6 letters may be matched fuzzily

# Removed for comparison only: Arabic diacritics and tatweel. No letter is mapped to another.
_MARKS = re.compile(r"[ً-ْٰـ]")
_ARABIC_WORD = re.compile(r"^[ء-يٰـً-ْ]+$")
_LATIN = re.compile(r"[A-Za-z]")
_ARABIC = re.compile(r"[؀-ۿ]")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def comparison_key(word: str) -> str:
    return _MARKS.sub("", word)


def canonical_bytes(data: dict) -> bytes:
    body = {k: v for k, v in data.items() if k != "sha256"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def compute_sha256(data: dict) -> str:
    return hashlib.sha256(canonical_bytes(data)).hexdigest()


def seal(data: dict) -> dict:
    """Return a copy with its sha256 set (used by the publishing step and tests)."""
    return {**data, "sha256": compute_sha256(data)}


@dataclass(frozen=True)
class Term:
    term: str
    kind: str
    keep_arabic: bool = False


@dataclass
class Glossary:
    course: str
    version: int
    sha256: str
    terms: List[Term]
    single: Dict[str, List[Term]] = field(default_factory=dict)          # word key -> terms
    multi: Dict[Tuple[str, ...], List[Term]] = field(default_factory=dict)  # word keys -> terms
    fuzzy: List[Tuple[str, Term]] = field(default_factory=list)          # long "word" aliases
    fuzzy_by_len: Dict[int, List[Tuple[str, Term]]] = field(default_factory=dict)
    # Lookup index only (never used to rewrite text): long aliases keyed with hamza-alif
    # forms folded, for fast candidate lookup when only hamza swaps fit the cost budget.
    fuzzy_folded: Dict[str, List[Tuple[str, Term]]] = field(default_factory=dict)
    never_correct: Set[str] = field(default_factory=set)

    @property
    def info(self) -> dict:
        return {"course": self.course, "version": self.version, "sha256": self.sha256}

    @property
    def max_phrase_words(self) -> int:
        return max((len(k) for k in self.multi), default=1)


def _fail(msg: str):
    raise GlossaryError(msg)


def _require_nfc(value: str, what: str):
    """Reject (never silently rewrite) text that is not in Unicode NFC form."""
    if unicodedata.normalize("NFC", value) != value:
        _fail(f"{what} {value!r} is not Unicode NFC; re-save it in NFC form")


def _validate_alias(term: Term, ar: str) -> Tuple[str, ...]:
    if not isinstance(ar, str) or not ar.strip() or ar != ar.strip():
        _fail(f"alias for '{term.term}' must be a non-empty string without outer spaces")
    _require_nfc(ar, f"alias of '{term.term}'")
    words = ar.split(" ")
    if any(not w or not _ARABIC_WORD.match(w) for w in words):
        _fail(f"alias '{ar}' for '{term.term}' must be Arabic words separated by single spaces")
    keys = tuple(comparison_key(w) for w in words)
    n = len(keys)
    if term.kind in ("phrase", "acronym_letters"):
        if n < 2:
            _fail(f"{term.kind} alias '{ar}' for '{term.term}' needs at least 2 words")
    elif n != 1:
        _fail(f"{term.kind} alias '{ar}' for '{term.term}' must be a single word")
    if term.kind == "word" and len(keys[0]) <= SHORT_MAX:
        _fail(f"alias '{ar}' for '{term.term}' has <= {SHORT_MAX} letters; use kind 'short'")
    if term.kind == "short" and len(keys[0]) > SHORT_MAX:
        _fail(f"short alias '{ar}' for '{term.term}' has more than {SHORT_MAX} letters")
    return keys


def build(data: dict) -> Glossary:
    """Validate a parsed glossary dict and build the index (approved aliases only)."""
    if not isinstance(data, dict):
        _fail("glossary must be a JSON object")
    if data.get("schema") != SCHEMA:
        _fail(f"unsupported glossary schema {data.get('schema')!r}; expected {SCHEMA}")
    course, version, digest = data.get("course"), data.get("version"), data.get("sha256")
    if not isinstance(course, str) or not course.strip():
        _fail("glossary 'course' is required")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        _fail("glossary 'version' must be a positive integer")
    if not isinstance(digest, str) or not _HEX64.match(digest):
        _fail("glossary 'sha256' must be 64 lowercase hex characters")
    actual = compute_sha256(data)
    if actual != digest:
        _fail(f"glossary {course} v{version} failed its integrity check (content was modified); "
              f"publish a new version instead of editing a used one")
    if not isinstance(data.get("terms"), list):
        _fail("glossary 'terms' must be a list")

    g = Glossary(course, version, digest, [])
    owner: Dict[Tuple[str, ...], str] = {}
    for raw in data["terms"]:
        if not isinstance(raw, dict):
            _fail("each term must be an object")
        name, kind = raw.get("term"), raw.get("kind")
        if not isinstance(name, str) or not name.strip() or not _LATIN.search(name) or _ARABIC.search(name):
            _fail(f"term {name!r} must be non-empty Latin text")
        if name != " ".join(name.split()):
            _fail(f"term {name!r} has leading, trailing, repeated or non-space whitespace")
        _require_nfc(name, "term")
        if kind not in KINDS:
            _fail(f"term '{name}' has unknown kind {kind!r}")
        if kind == "phrase" and len(name.split()) < 2:
            _fail(f"phrase term '{name}' must have at least 2 words")
        term = Term(name, kind, bool(raw.get("keep_arabic", False)))
        g.terms.append(term)
        for alias in raw.get("aliases", []):
            if not isinstance(alias, dict) or alias.get("status") not in STATUSES:
                _fail(f"alias of '{name}' needs a status in {sorted(STATUSES)}")
            keys = _validate_alias(term, alias.get("ar"))
            if alias["status"] != "approved":
                continue
            if keys in owner and owner[keys] != name:
                _fail(f"alias '{alias['ar']}' is approved for both '{owner[keys]}' and '{name}'")
            if keys in owner:
                continue
            owner[keys] = name
            if len(keys) == 1:
                g.single.setdefault(keys[0], []).append(term)
                if kind == "word" and len(keys[0]) >= FUZZY_MIN:
                    g.fuzzy.append((keys[0], term))
            else:
                g.multi.setdefault(keys, []).append(term)
    never = data.get("never_correct", [])
    if not isinstance(never, list) or not all(isinstance(w, str) and w for w in never):
        _fail("'never_correct' must be a list of words")
    for w in never:
        _require_nfc(w, "never_correct entry")
    g.never_correct = {comparison_key(w) for w in never}
    g.fuzzy.sort(key=lambda x: (x[0], x[1].term))
    for key, term in g.fuzzy:
        g.fuzzy_by_len.setdefault(len(key), []).append((key, term))
        g.fuzzy_folded.setdefault(hamza_fold(key), []).append((key, term))
    return g


_HAMZA_FOLD = str.maketrans("أإآ", "ااا")


def hamza_fold(key: str) -> str:
    """Index key only; matching scores still charge 0.5 per hamza-alif swap."""
    return key.translate(_HAMZA_FOLD)


def load_glossary(path) -> Glossary:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GlossaryError(f"glossary not found: {path}") from None
    except (OSError, ValueError) as exc:
        raise GlossaryError(f"cannot read glossary {path}: {exc}") from exc
    return build(data)
