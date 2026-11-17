import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List

from .errors import PhraseError

# Built-in quick phrases for a student in a lecture. Ids d1, d2, ... are fixed.
DEFAULT_PHRASES = [
    "مرحباً",
    "شكراً لك",
    "نعم",
    "لا",
    "عندي سؤال",
    "ممكن تعيد الشرح لو سمحت؟",
    "لم أفهم هذه النقطة",
    "ممكن تتكلم أبطأ لو سمحت؟",
    "أحتاج مساعدة",
    "أحتاج وقتاً إضافياً",
    "هل يمكنني المشاركة؟",
    "أريد الخروج قليلاً لو سمحت",
    "I have a question.",
    "Could you repeat that, please?",
    "Thank you.",
]


@dataclass
class Phrase:
    id: str
    text: str
    custom: bool = False


class PhraseBook:
    """Default quick phrases plus custom ones stored in a JSON file.

    Defaults are read-only; custom phrases (ids c1, c2, ...) can be added, edited, removed.
    """

    def __init__(self, path):
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.is_file():
            return {"next_id": 1, "phrases": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {"next_id": int(data["next_id"]),
                    "phrases": [{"id": str(p["id"]), "text": str(p["text"])} for p in data["phrases"]]}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise PhraseError(f"Cannot read phrases file {self.path}: {exc}") from exc

    def _save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            raise PhraseError(f"Cannot write phrases file {self.path}: {exc}") from exc

    @staticmethod
    def _text(text: str) -> str:
        text = " ".join((text or "").split())
        if not text:
            raise PhraseError("Phrase text is empty")
        return text

    def _custom(self, data: dict, phrase_id: str) -> dict:
        if str(phrase_id).startswith("d") and any(p.id == phrase_id for p in self.defaults()):
            raise PhraseError(f"Default phrase '{phrase_id}' cannot be changed")
        for p in data["phrases"]:
            if p["id"] == phrase_id:
                return p
        raise PhraseError(f"No phrase with id '{phrase_id}'")

    @staticmethod
    def defaults() -> List[Phrase]:
        return [Phrase(f"d{i}", text) for i, text in enumerate(DEFAULT_PHRASES, 1)]

    def list(self) -> List[Phrase]:
        return self.defaults() + [Phrase(p["id"], p["text"], True) for p in self._load()["phrases"]]

    def get(self, phrase_id: str) -> Phrase:
        for p in self.list():
            if p.id == phrase_id:
                return p
        raise PhraseError(f"No phrase with id '{phrase_id}'")

    def add(self, text: str) -> Phrase:
        data = self._load()
        phrase = Phrase(f"c{data['next_id']}", self._text(text), True)
        data["phrases"].append({"id": phrase.id, "text": phrase.text})
        data["next_id"] += 1
        self._save(data)
        return phrase

    def update(self, phrase_id: str, text: str) -> Phrase:
        data = self._load()
        entry = self._custom(data, phrase_id)
        entry["text"] = self._text(text)
        self._save(data)
        return Phrase(entry["id"], entry["text"], True)

    def remove(self, phrase_id: str) -> None:
        data = self._load()
        data["phrases"].remove(self._custom(data, phrase_id))
        self._save(data)

    def to_dicts(self) -> List[dict]:
        return [asdict(p) for p in self.list()]
