"""Counting, ordinals and lists in Arabic and English, in a gender-neutral form of address."""
from typing import Iterable, List, Optional

# noun: (singular, dual, plural 3-10, singular after 11-99, gender), (English singular, plural)
NOUNS = {
    "day": (("يوم", "يومين", "أيام", "يوماً", "m"), ("day", "days")),
    "hour": (("ساعة", "ساعتين", "ساعات", "ساعة", "f"), ("hour", "hours")),
    "minute": (("دقيقة", "دقيقتين", "دقائق", "دقيقة", "f"), ("minute", "minutes")),
    "page": (("صفحة", "صفحتين", "صفحات", "صفحة", "f"), ("page", "pages")),
    "slide": (("سلايد", "سلايدين", "سلايدات", "سلايداً", "m"), ("slide", "slides")),
    "sheet": (("ورقة", "ورقتين", "أوراق", "ورقة", "f"), ("sheet", "sheets")),
    "topic": (("موضوع", "موضوعين", "مواضيع", "موضوعاً", "m"), ("topic", "topics")),
    "image": (("صورة", "صورتين", "صور", "صورة", "f"), ("image", "images")),
    "table": (("جدول", "جدولين", "جداول", "جدولاً", "m"), ("table", "tables")),
    "chart": (("مخطط", "مخططين", "مخططات", "مخططاً", "m"), ("chart", "charts")),
    "column": (("عمود", "عمودين", "أعمدة", "عموداً", "m"), ("column", "columns")),
    "row": (("صف", "صفين", "صفوف", "صفاً", "m"), ("row", "rows")),
    "question": (("سؤال", "سؤالين", "أسئلة", "سؤالاً", "m"), ("question", "questions")),
    "attempt": (("محاولة", "محاولتين", "محاولات", "محاولة", "f"), ("attempt", "attempts")),
    "attachment": (("مرفق", "مرفقين", "مرفقات", "مرفقاً", "m"), ("attachment", "attachments")),
    "message": (("رسالة", "رسالتين", "رسائل", "رسالة", "f"), ("message", "messages")),
    "notification": (("إشعار", "إشعارين", "إشعارات", "إشعاراً", "m"), ("notification", "notifications")),
}

_ORDINALS = ["الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن",
             "التاسع", "العاشر"]
_ORDINALS += ["الحادي عشر"] + [f"{o} عشر" for o in _ORDINALS[1:9]] + ["العشرون"]
_EN_ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"]


def number(n) -> str:
    """12 -> "12", 2.0 -> "2", 2.5 -> "2.5"."""
    return str(int(n)) if float(n).is_integer() else str(n)


def count(n, noun: str, lang: str, one: bool = True) -> str:
    """'3 أيام', 'يومين', '11 يوماً', 'يوم واحد' (or 'يوم' when one=False); '3 days'."""
    ar, en = NOUNS[noun]
    if lang == "en":
        return f"{number(n)} {en[0] if n == 1 else en[1]}"
    singular, dual, plural, accusative, gender = ar
    if not float(n).is_integer():
        return f"{number(n)} {singular}"
    n = int(n)
    if n == 1:
        return f"{singular} {'واحد' if gender == 'm' else 'واحدة'}" if one else singular
    if n == 2:
        return dual
    rest = n % 100
    if 3 <= rest <= 10:
        return f"{n} {plural}"
    if 11 <= rest <= 99:
        return f"{n} {accusative}"
    return f"{n} {singular}"                                # 0, 100, 200, 101, 102 ...


def ordinal(n: int, lang: str) -> Optional[str]:
    """'الثاني' / 'second' up to 20 (Arabic, masculine) or 10 (English); else None."""
    table = _EN_ORDINALS if lang == "en" else _ORDINALS
    return table[n - 1] if 1 <= n <= len(table) else None


def join(items: Iterable[str], lang: str) -> str:
    return (", " if lang == "en" else "، ").join(i for i in items if i)


def sentence(text: str) -> str:
    text = " ".join(str(text).split())
    return text if not text or text.endswith(tuple(".!?؟…:")) else f"{text}."


def sentences(parts: Iterable[Optional[str]]) -> str:
    """Joins the non-empty parts as sentences (missing information is simply left out)."""
    return " ".join(sentence(p) for p in parts if p and str(p).strip())


def letters(lang: str) -> List[str]:
    """Option letters: أ ب ج د ... / A B C D ..."""
    if lang == "en":
        return [chr(ord("A") + i) for i in range(26)]
    return ["أ", "ب", "ج", "د", "هـ", "و", "ز", "ح", "ط", "ي", "ك", "ل", "م", "ن"]
