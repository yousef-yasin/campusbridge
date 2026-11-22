"""The narrator's output: a list of segments, each ready for the text-to-speech module."""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List

KINDS = ("intro", "topic_change", "position", "heading", "content", "list", "notes", "image",
         "table", "table_row", "chart", "outro", "question", "options", "confirm", "time_warning",
         "assignment", "summary", "message", "notification", "emergency", "navigation",
         "ocr_notice", "handwritten", "references")


@dataclass
class Segment:
    """text: what to say. kind: see KINDS. position: where it belongs (unit, topic, question, ...)."""
    text: str
    kind: str
    position: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def speech_text(segments: Iterable[Segment]) -> str:
    """All segments as one text for text-to-speech (blank lines between segments)."""
    return "\n\n".join(s.text for s in segments if s.text)


def to_dicts(segments: Iterable[Segment]) -> List[Dict[str, Any]]:
    return [s.to_dict() for s in segments]
