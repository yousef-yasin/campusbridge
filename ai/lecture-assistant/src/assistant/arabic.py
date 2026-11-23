"""Text normalisation and words for keyword search (BM25), Arabic and English.

Arabic: no diacritics or tatweel, أ/إ/آ/ٱ -> ا, ؤ -> و, ئ -> ي, ة -> ه, ى -> ي, Arabic-Indic digits
-> 0-9, and the article and one-letter prefixes (ال، وال، بال، لل، ...) removed. English: lower
case, a final plural "s" removed. Very common words are left out.
"""
import re
from typing import List

_HARAKAT = re.compile(r"[ً-ٰٟۖ-ۭـ]")      # diacritics, Quranic marks, tatweel
_WORDS = re.compile(r"[ء-ي0-9]+|[a-z0-9]+")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_PREFIXES = ("وال", "بال", "فال", "كال", "لل", "ال")

STOP = set("""
في من على الى عن مع هو هي هم هذا هذه ذلك تلك التي الذي الذين ما ماذا لماذا كيف متى اين هل لا لم لن
ان او ثم كل بين عند بعد قبل كان كانت يكون تكون اي انه انها و ف ب ل ك قد لقد ايش شو وش اشرح اشرحلي
لي لنا عن يعني بدي اريد ممكن كم يجب مصطلح معني عرف
the a an of to in on at for and or is are was were be been it its this that these those what
which who how why when where does do did can could with from by as about into than then there
explain tell me please term meaning define
""".split())


def normalize(text: str) -> str:
    text = _HARAKAT.sub("", text or "").translate(_DIGITS).lower()
    text = re.sub("[أإآٱ]", "ا", text)
    return text.replace("ؤ", "و").replace("ئ", "ي").replace("ة", "ه").replace("ى", "ي")


def _stem(word: str) -> str:
    if word[0] >= "ء":                                   # Arabic
        for prefix in _PREFIXES:
            if word.startswith(prefix) and len(word) - len(prefix) >= 2:
                return word[len(prefix):]
        return word
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def words(text: str) -> List[str]:
    """Search words of a text: normalised, stemmed lightly, without common words."""
    out = []
    for w in _WORDS.findall(normalize(text)):
        if w in STOP or (w[0] in "وف" and w[1:] in STOP):        # «وكم», «فما»
            continue
        w = _stem(w)
        if w and w not in STOP and (len(w) > 1 or w.isdigit()):
            out.append(w)
    return out


def with_variants(tokens: List[str]) -> List[str]:
    """Document words plus each word without a leading و/ف/ب/ل/ك («وتعيش» also counts as «تعيش»).
    Only on the document side: a question word then matches either form."""
    out = list(tokens)
    out += [w[1:] for w in tokens if len(w) >= 4 and w[0] in "وفبلك" and w[0] >= "ء"]
    return out


def language_of(text: str) -> str:
    """'ar', 'en' or 'mixed' from the share of Arabic and Latin letters."""
    arabic = len(re.findall(r"[ء-ي]", text or ""))
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    total = arabic + latin
    if not total:
        return "en"
    share = arabic / total
    return "ar" if share >= 0.8 else ("en" if share <= 0.2 else "mixed")
