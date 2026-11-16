import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

# Arabic diacritics (tashkeel) and tatweel are ignored when searching; alef forms are unified.
_AR_MARKS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_AR_ALEF = re.compile(r"[آأإ]")


def normalize(text: str) -> str:
    text = _AR_MARKS.sub("", text)
    text = _AR_ALEF.sub("ا", text)
    return text.casefold()


def _ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


@dataclass
class Segment:
    start: float
    end: float
    text: str
    slide: Optional[int] = None


@dataclass
class Transcript:
    segments: List[Segment] = field(default_factory=list)
    language: str = "ar"

    @property
    def full_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())

    def search(self, keyword: str) -> List[Segment]:
        key = normalize(keyword.strip())
        if not key:
            return []
        return [s for s in self.segments if key in normalize(s.text)]

    def to_text(self) -> str:
        lines = []
        for s in self.segments:
            slide = f" [slide {s.slide}]" if s.slide is not None else ""
            lines.append(f"[{_ts(s.start)} - {_ts(s.end)}]{slide} {s.text.strip()}")
        return "\n".join(lines) + "\n"

    def save(self, path) -> Path:
        """Write a timestamped UTF-8 .txt and a sibling .json (segments + full_text)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_text(), encoding="utf-8")
        data = {"language": self.language, "full_text": self.full_text,
                "segments": [asdict(s) for s in self.segments]}
        path.with_suffix(".json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, json_path) -> "Transcript":
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
        return cls([Segment(**s) for s in data["segments"]], data.get("language", "ar"))
