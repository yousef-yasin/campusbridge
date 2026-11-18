"""Shared helpers for narrating platform data (quiz, assignment, chat, notifications)."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import NarratorConfig
from .dates import say_remaining, say_until, say_when
from .errors import InputError
from .words import count, join

# "new" after a count, Arabic: (1, 2, 3-10, 11+)
_NEW = {"message": ("جديدة", "جديدتين", "جديدة", "جديدة"),
        "notification": ("جديد", "جديدين", "جديدة", "جديداً")}


class Narrator:
    """Base: language, time zone and "now" for every platform narrator."""

    def __init__(self, config: Optional[NarratorConfig] = None, now: Optional[datetime] = None):
        self.config = (config or NarratorConfig.from_env()).validate()
        self.lang = self.config.phrase_language
        self.en = self.lang == "en"
        self.tz = self.config.tz()
        self.now = now.astimezone(self.tz) if now else self.config.now()

    def when(self, value, field: str = "date") -> str:
        return say_when(value, self.lang, self.tz, self.now, field)

    def remaining(self, value, field: str = "deadline") -> str:
        return say_remaining(value, self.lang, self.tz, self.now, field)

    def until(self, value, field: str = "date") -> str:
        return say_until(value, self.lang, self.tz, self.now, field)

    def count(self, n, noun: str, one: bool = True) -> str:
        return count(n, noun, self.lang, one)

    def join(self, items) -> str:
        return join(items, self.lang)

    def you_have(self, n: int, noun: str) -> str:
        """'عندك 3 رسائل جديدة' / 'You have 3 new messages'."""
        if self.en:
            return f"You have {n} new {noun}{'' if n == 1 else 's'}."
        one, two, few, many = _NEW[noun]
        if n == 1:
            return f"عندك {count(1, noun, 'ar', one=False)} {one}."
        if n == 2:
            return f"عندك {count(2, noun, 'ar')} {two}."
        return f"عندك {count(n, noun, 'ar')} {few if 3 <= n % 100 <= 10 else many}."

    def attachments(self, items: Any, verb_ar: str = "يحتوي") -> Optional[str]:
        """'يحتوي على مرفقين: a.pdf، b.docx' / '2 attachments: a.pdf, b.docx'; None if not given."""
        if items is None:
            return None
        names = attachment_names(items)
        if not names:
            return "No attachments" if self.en else "بدون مرفقات"
        if self.en:
            return f"{self.count(len(names), 'attachment')}: {self.join(names)}"
        return f"{verb_ar} على {self.count(len(names), 'attachment')}: {self.join(names)}"


def attachment_names(items: Any) -> List[str]:
    if not isinstance(items, list):
        raise InputError("attachments must be a list of names or {\"name\": ...} objects")
    names = []
    for item in items:
        name = item.get("name") if isinstance(item, dict) else item
        if name and str(name).strip():
            names.append(str(name).strip())
    return names


def require_dict(data: Any, what: str) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise InputError(f"{what} must be a JSON object")
    return data


def text_field(data: Dict[str, Any], key: str) -> Optional[str]:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        raise InputError(f"{key} must be text")
    value = " ".join(str(value).split())
    return value or None
