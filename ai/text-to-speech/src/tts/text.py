"""Text preparation: cleaning, sentence splitting, language detection, number expansion."""
import re
import unicodedata
from dataclasses import dataclass
from typing import List

_LATIN = "A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u024F"
_AR_LETTER = re.compile("[\u0621-\u064A\u066E-\u06D3]")
_LATIN_LETTER = re.compile(f"[{_LATIN}]")
_SPEAKABLE = re.compile(r"[^\W_]")
# tatweel, zero-width and bidi control characters, BOM
_DROP = re.compile("[\u0640\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]")
# Arabic-Indic and Persian digits, Arabic decimal and thousands separators
_DIGITS = str.maketrans(
    "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
    "\u06F0\u06F1\u06F2\u06F3\u06F4\u06F5\u06F6\u06F7\u06F8\u06F9\u066B\u066C",
    "01234567890123456789.,")
_SENTENCE_END = re.compile("(?<=[.!?\u061F\u061B\u2026])\\s+|\\n+")   # . ! ? ؟ ؛ …
_CLAUSE_END = re.compile("(?<=[\u060C,;:])\\s+")                      # ، , ; :
_NUMBER = re.compile(r"\d+(?:,\d{3})+(?:\.\d+)?%?|\d+(?:\.\d+)?%?")
_PIECES = re.compile(f"[{_LATIN}][{_LATIN}'\u2019\\-]*|[^{_LATIN}]+")
_SPACE_BEFORE_PUNCT = re.compile(" ([.,!?\u061F\u060C\u061B:\u2026])")
_SYMBOLS = {
    "&": {"ar": "و", "en": "and"},
    "+": {"ar": "زائد", "en": "plus"},
    "=": {"ar": "يساوي", "en": "equals"},
    "@": {"ar": "آت", "en": "at"},
}
_POINT = {"ar": "فاصلة", "en": "point"}
_PERCENT = {"ar": "بالمئة", "en": "percent"}


@dataclass
class Segment:
    """A piece of text spoken by one voice."""
    lang: str   # "ar" or "en"
    text: str


def clean(text: str) -> str:
    """Unify digits and whitespace; newlines are kept as sentence breaks."""
    text = unicodedata.normalize("NFKC", text).translate(_DIGITS)
    text = _DROP.sub("", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    return re.sub(r" ?\n[ \n]*", "\n", text).strip()


def split_sentences(text: str, max_chars: int = 250) -> List[str]:
    """Split on sentence punctuation and newlines; over-long sentences split at commas/words."""
    out = []
    for sentence in _SENTENCE_END.split(text):
        sentence = sentence.strip()
        if sentence:
            out.extend(_wrap(sentence, max_chars))
    return out


def _wrap(sentence: str, max_chars: int) -> List[str]:
    if max_chars <= 0 or len(sentence) <= max_chars:
        return [sentence]
    units = []
    for clause in _CLAUSE_END.split(sentence):
        units.extend([clause] if len(clause) <= max_chars else clause.split(" "))
    out, current = [], ""
    for unit in units:
        if current and len(current) + 1 + len(unit) > max_chars:
            out.append(current)
            current = unit
        else:
            current = f"{current} {unit}".strip()
    return out + [current] if current else out


def detect_language(text: str, fallback: str = "ar") -> str:
    """'ar' or 'en' by counting words of each script; ties and no words -> fallback.

    Words are counted, not letters: English terms are long, so a letter count would call
    an Arabic sentence with two English terms English.
    """
    words = text.split()
    ar = sum(1 for w in words if _AR_LETTER.search(w))
    en = sum(1 for w in words if _LATIN_LETTER.search(w) and not _AR_LETTER.search(w))
    if ar == en:
        return fallback
    return "ar" if ar > en else "en"


def _spell_digits(digits: str, lang: str) -> str:
    from num2words import num2words
    return " ".join(num2words(int(d), lang=lang) for d in digits)


def _integer(digits: str, lang: str) -> str:
    from num2words import num2words
    if (len(digits) > 1 and digits[0] == "0") or len(digits) > 15:
        return _spell_digits(digits, lang)   # phone numbers, codes, IDs
    words = num2words(int(digits), lang=lang)
    return words.replace(" و ", " و") if lang == "ar" else words


def number_to_words(token: str, lang: str) -> str:
    """'1,250' / '3.5' / '40%' -> words in the given language."""
    percent = token.endswith("%")
    whole, _, frac = token.rstrip("%").replace(",", "").partition(".")
    words = _integer(whole, lang)
    if frac:
        spell = lang == "en" or frac[0] == "0" or len(frac) > 3
        words += f" {_POINT[lang]} " + (_spell_digits(frac, lang) if spell else _integer(frac, lang))
    return words + (f" {_PERCENT[lang]}" if percent else "")


def expand(sentence: str, lang: str) -> str:
    """Replace numbers and a few symbols with words in the sentence language."""
    def repl(match):
        try:
            return f" {number_to_words(match.group(0), lang)} "
        except Exception:      # unsupported number: leave the digits for the engine
            return match.group(0)
    sentence = _NUMBER.sub(repl, sentence)
    for symbol, words in _SYMBOLS.items():
        sentence = sentence.replace(symbol, f" {words[lang]} ")
    sentence = re.sub(r"\s+", " ", sentence).strip()
    return _SPACE_BEFORE_PUNCT.sub(r"\1", sentence)


def split_by_language(sentence: str, default: str) -> List[Segment]:
    """Split a sentence into Arabic and English runs; punctuation stays with the run before it."""
    runs, pending = [], ""
    for ti, token in enumerate(sentence.split()):
        for pi, piece in enumerate(_PIECES.findall(token)):
            sep = " " if pi == 0 and ti > 0 else ""
            if _LATIN_LETTER.search(piece):
                kind = "en"
            elif _AR_LETTER.search(piece):
                kind = "ar"
            else:
                kind = None
            if kind is None:
                if runs:
                    runs[-1].text += sep + piece
                else:
                    pending += sep + piece
            elif runs and runs[-1].lang == kind:
                runs[-1].text += sep + piece
            else:
                runs.append(Segment(kind, pending + sep + piece))
                pending = ""
    if not runs:
        runs = [Segment(default, sentence)]
    return [Segment(r.lang, r.text.strip()) for r in runs]


def split_paragraphs(text: str, max_chars: int) -> List[str]:
    """Raw text for engines that normalize by themselves: only whitespace at the ends is cut.

    Text within max_chars stays in one piece. Longer text is split at paragraph breaks only
    (blank lines, else single line breaks) and paragraphs are packed up to max_chars; one
    paragraph longer than max_chars is kept whole.
    """
    text = (text or "").strip()
    if not _SPEAKABLE.search(text):
        return []
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    separator = "\n\n" if re.search(r"\n[^\S\n]*\n", text) else "\n"
    pattern = r"\n[^\S\n]*\n\s*" if separator == "\n\n" else r"\n\s*"
    out, current = [], ""
    for paragraph in (p.strip() for p in re.split(pattern, text)):
        if not paragraph:
            continue
        if current and len(current) + len(separator) + len(paragraph) > max_chars:
            out.append(current)
            current = paragraph
        else:
            current = f"{current}{separator}{paragraph}" if current else paragraph
    out.append(current)
    return [p for p in out if _SPEAKABLE.search(p)]


def prepare(text: str, language: str = "auto", fallback: str = "ar",
            max_chars: int = 250, split_languages: bool = True) -> List[Segment]:
    """Full pipeline: text -> ordered segments, each tagged with the voice language.

    auto: each sentence gets its dominant language (numbers are read in that language),
    then mixed sentences are split so every part is spoken by its own voice.
    ar/en: everything is spoken by that one voice.
    split_languages=False (one multilingual voice): sentences are kept whole; numbers are
    still read in the language of their sentence.
    """
    segments = []
    for sentence in split_sentences(clean(text), max_chars):
        lang = detect_language(sentence, fallback) if language == "auto" else language
        sentence = expand(sentence, lang)
        split = split_languages and language == "auto"
        parts = split_by_language(sentence, lang) if split else [Segment(lang, sentence)]
        segments.extend(p for p in parts if _SPEAKABLE.search(p.text))
    return segments
