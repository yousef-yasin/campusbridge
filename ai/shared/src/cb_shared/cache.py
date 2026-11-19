"""Reviewable JSON cache of AI results, one file per result.

Each file holds the automatic result, a "review" state ("draft" until a person sets
"approved") and a "manual" section whose non-empty fields replace the automatic ones.
"""
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

REVIEW_STATES = ("draft", "approved")


class ReviewCache:
    def __init__(self, folder):
        self.folder = Path(folder)

    def path(self, digest: str, model: str, language: str, version: int, kind: str) -> Path:
        model = re.sub(r"[^A-Za-z0-9._-]+", "_", model)
        return self.folder / f"{digest[:16]}__{kind}__{model}__{language}__v{version}.json"

    def load(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if record.get("review") not in REVIEW_STATES:
            record["review"] = "draft"
        return record

    def save(self, path: Path, record: Dict[str, Any]) -> None:
        record.setdefault("created", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        record.setdefault("review", "draft")
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("AI result cache not written: %s", exc)


def merged(automatic: Dict[str, Any], manual: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The automatic result with every non-empty manual field on top."""
    out = dict(automatic)
    for key, value in (manual or {}).items():
        if key != "note" and value not in (None, "", [], {}):
            out[key] = value
    return out


def has_manual(manual: Optional[Dict[str, Any]]) -> bool:
    return any(v not in (None, "", [], {}) for k, v in (manual or {}).items() if k != "note")
