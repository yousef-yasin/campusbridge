"""Saved questions and answers (a JSON file now; a database table later), without personal data.

A record has a random conversation id (made by the caller, not a student id), the course, the
question, the answer, its sources and status, and the time. Nothing about the student.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def new_conversation() -> str:
    return uuid.uuid4().hex[:12]


class QALog:
    """append(record) and recent(conversation, n): the interface a database version will keep."""

    FIELDS = ("conversation", "courses", "question", "answer", "status", "intent", "sources", "problems", "model")

    def __init__(self, path):
        self.path = Path(path)

    def _load(self) -> List[Dict[str, Any]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except ValueError:
            return []                                       # a broken log never stops the assistant

    def append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        row = {k: record.get(k) for k in self.FIELDS}
        row["time"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = self._load()
        rows.append(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        return row

    def recent(self, conversation: str, n: int = 3) -> List[Dict[str, Any]]:
        """The last n exchanges of a conversation, oldest first."""
        return [r for r in self._load() if r.get("conversation") == conversation][-n:] if conversation else []
