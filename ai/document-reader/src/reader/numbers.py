"""Checking the numbers of an image description against the image itself.

A vision model sometimes calculates or rounds (it once wrote 94% where the image says 95.4%).
Every number in a description must also appear in the text read from the image (or in the
page text sent with it). Numbers are found as digits (Western or Arabic-Indic) and as words in
Arabic or English ("أربعة وتسعون", "ninety-four"), and compared by value: 95.40 = 95.4, .97 = 0.97.

Whole numbers from 0 to 10 are not checked: descriptions use them to count what is drawn
("أربعة أنواع", "three curves"), which no text in the image contains.
"""
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Iterable, List, Set

_SMALL = 10
_DIGITS = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d*\.\d+|\d+")
_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")
_HARAKAT = re.compile(r"[ً-ْٰـ]")

# Arabic number words, normalised (أ/إ/آ -> ا, ة -> ه, ى -> ي, no diacritics)
_AR_UNITS = {
    "صفر": 0, "واحد": 1, "واحده": 1, "احد": 1, "احدي": 1, "اثنان": 2, "اثنين": 2, "اثنتان": 2,
    "اثنتين": 2, "ثلاث": 3, "ثلاثه": 3, "اربع": 4, "اربعه": 4, "خمس": 5, "خمسه": 5, "ست": 6,
    "سته": 6, "سبع": 7, "سبعه": 7, "ثمان": 8, "ثماني": 8, "ثمانيه": 8, "تسع": 9, "تسعه": 9,
}
_AR_TEN = {"عشر": 10, "عشره": 10}
_AR_TENS = {f"{root}{end}": value for root, value in
            (("عشر", 20), ("ثلاث", 30), ("اربع", 40), ("خمس", 50), ("ست", 60), ("سبع", 70),
             ("ثمان", 80), ("تسع", 90)) for end in ("ون", "ين")}
_AR_HUNDRED = {"مائه", "مئه"}
_AR_HUNDREDS = {"مائتان": 200, "مائتين": 200, "مئتان": 200, "مئتين": 200}
_AR_HUNDREDS.update({f"{root}{h}": value * 100 for root, value in
                     (("ثلاث", 3), ("اربع", 4), ("خمس", 5), ("ست", 6), ("سبع", 7), ("ثمان", 8),
                      ("ثماني", 8), ("تسع", 9)) for h in _AR_HUNDRED})
_AR_THOUSAND = {"الف": 1000, "الفان": 2000, "الفين": 2000}
_AR_POINT = {"فاصله", "فاصل"}

_EN_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen".split())}
_EN_TENS = {w: (i + 2) * 10 for i, w in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split())}


def _canonical(text: str) -> str:
    try:
        value = abs(Decimal(text.replace(",", "")))
    except InvalidOperation:
        return text
    return str(int(value)) if value == value.to_integral_value() else format(value.normalize(), "f")


def _ar_word(token: str):
    """The value of one Arabic number word (with و / ال / ب prefixes), else None."""
    for prefix in ("", "و", "ال", "وال", "ب", "بال"):
        if token.startswith(prefix):
            word = token[len(prefix):]
            for table in (_AR_UNITS, _AR_TEN, _AR_TENS, _AR_HUNDREDS, _AR_THOUSAND):
                if word in table:
                    return table[word], prefix.startswith("و")
            if word in _AR_HUNDRED and "ال" not in prefix:          # not بالمائة (percent)
                return 100, prefix.startswith("و")
    return None


def _ar_integer(tokens: List[str], i: int):
    """Parse an Arabic number phrase at tokens[i]: (value, next index) or None."""
    first = _ar_word(tokens[i])
    if first is None:
        return None
    value, i = first[0], i + 1
    if i < len(tokens) and tokens[i] in _AR_TEN and 1 <= value <= 9:      # ثلاثة عشر
        value, i = value + 10, i + 1
    if i < len(tokens) and tokens[i] in _AR_HUNDRED and 1 <= value <= 9:  # ثلاث مائة
        value, i = value * 100, i + 1
    last = value
    while i < len(tokens):
        nxt = _ar_word(tokens[i])
        if nxt is None or not nxt[1]:                                     # needs "و..."
            break
        n = nxt[0]
        joins = ((last >= 100 and last % 100 == 0 and n < last)          # مائة وخمسة
                 or (1 <= last <= 9 and n in _AR_TENS.values()))          # أربعة وتسعون
        if not joins:                                                     # "اثنين وثلاثة": two numbers
            break
        value, last, i = value + n, n, i + 1
        if i < len(tokens) and tokens[i] in _AR_TEN and 1 <= n <= 9:
            value, last, i = value + 10, value + 10, i + 1
    return value, i


def _arabic_numbers(text: str) -> List[str]:
    text = _HARAKAT.sub("", unicodedata.normalize("NFKC", text))
    text = re.sub("[أإآ]", "ا", text).replace("ة", "ه").replace("ى", "ي")
    found: List[str] = []
    for part in re.split(r"[،,.؛;:!?؟\n()]", text):                     # never join across punctuation
        found += _arabic_part(re.findall(r"[ء-ي]+", part))
    return found


def _arabic_part(tokens: List[str]) -> List[str]:
    found, i = [], 0
    while i < len(tokens):
        parsed = _ar_integer(tokens, i)
        if parsed is None:
            i += 1
            continue
        value, i = parsed
        number = str(value)
        if i + 1 < len(tokens) and tokens[i] in _AR_POINT:               # خمسة وتسعون فاصلة أربعة
            decimal = _ar_integer(tokens, i + 1)
            if decimal:
                number, i = f"{value}.{decimal[0]}", decimal[1]
        found.append(number)
    return found


def _en_below_100(tokens: List[str], i: int):
    """(value, next index) for "ninety four", "seventeen", ... at tokens[i], else None."""
    if i >= len(tokens):
        return None
    if tokens[i] in _EN_TENS:
        value, i = _EN_TENS[tokens[i]], i + 1
        if i < len(tokens) and 1 <= _EN_UNITS.get(tokens[i], 0) <= 9:
            value, i = value + _EN_UNITS[tokens[i]], i + 1
        return value, i
    if tokens[i] in _EN_UNITS:
        return _EN_UNITS[tokens[i]], i + 1
    return None


def _english_numbers(text: str) -> List[str]:
    tokens = re.findall(r"[a-z]+", text.lower())
    found, i = [], 0
    while i < len(tokens):
        parsed = _en_below_100(tokens, i)
        if parsed is None:
            i += 1
            continue
        value, i = parsed
        if i < len(tokens) and tokens[i] == "hundred":                    # two hundred and five
            value, i = value * 100, i + 1
            j = i + 1 if i < len(tokens) and tokens[i] == "and" else i
            rest = _en_below_100(tokens, j)
            if rest:
                value, i = value + rest[0], rest[1]
        number = str(value)
        if i < len(tokens) and tokens[i] == "point":                     # ninety five point four
            digits = []
            i += 1
            while i < len(tokens) and tokens[i] in _EN_UNITS and _EN_UNITS[tokens[i]] <= 9:
                digits.append(str(_EN_UNITS[tokens[i]]))
                i += 1
            if digits:
                number = f"{value}.{''.join(digits)}"
        found.append(number)
    return found


def numbers_in(text: str) -> List[str]:
    """Every number in the text, as canonical strings ("95.4", "2022", "0.9713")."""
    if not text:
        return []
    plain = unicodedata.normalize("NFKC", text).translate(_INDIC)
    digits = [_canonical(m) for m in _DIGITS.findall(plain)]
    words = _arabic_numbers(plain) + _english_numbers(re.sub(r"[-‐–]", " ", plain))
    return digits + [_canonical(w) for w in words]


def _checked(number: str) -> bool:
    return not ("." not in number and int(number) <= _SMALL)


def unverified_numbers(described: Iterable[str], sources: Iterable[str]) -> List[str]:
    """Numbers in the described texts that appear in none of the source texts."""
    allowed: Set[str] = set()
    for text in sources:
        allowed.update(numbers_in(text))
    missing: List[str] = []
    for text in described:
        for number in numbers_in(text):
            if _checked(number) and number not in allowed and number not in missing:
                missing.append(number)
    return missing


def has_number(text: str, numbers: Iterable[str]) -> bool:
    return bool(set(numbers_in(text)) & set(numbers))
