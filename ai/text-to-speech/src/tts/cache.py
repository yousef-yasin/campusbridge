import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class AudioCache:
    """Audio clips on disk, keyed by engine + voice + speed + text (+ model and style).

    Cache problems never fail a synthesis: a clip that cannot be read or written
    is simply synthesized again.
    """

    def __init__(self, directory, enabled: bool = True):
        self.directory = Path(directory)
        self.enabled = enabled

    @staticmethod
    def key(engine: str, voice: str, speed: float, text: str, extra=None) -> str:
        """extra: more engine settings that change the audio (Gemini: model and style)."""
        parts = [engine, voice, round(float(speed), 2), text] + ([extra] if extra else [])
        raw = json.dumps(parts, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _path(self, key: str, ext: str) -> Path:
        return self.directory / f"{key}.{ext}"

    def get(self, key: str, ext: str) -> Optional[bytes]:
        if not self.enabled:
            return None
        try:
            return self._path(key, ext).read_bytes() or None
        except OSError:
            return None

    def put(self, key: str, ext: str, data: bytes) -> None:
        if not self.enabled:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            tmp = self._path(key, f"{ext}.{os.getpid()}.tmp")
            tmp.write_bytes(data)
            tmp.replace(self._path(key, ext))
        except OSError as exc:
            log.warning("Audio cache not written: %s", exc)

    def clear(self) -> int:
        """Delete all cached clips; returns how many were removed."""
        count = 0
        if self.directory.is_dir():
            for path in self.directory.iterdir():
                if path.is_file() and path.suffix in (".wav", ".mp3", ".tmp"):
                    try:
                        path.unlink()
                        count += 1
                    except OSError:
                        pass
        return count
