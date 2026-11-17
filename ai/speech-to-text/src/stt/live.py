import logging
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import numpy as np

from .errors import STTError
from .transcriber import Transcriber
from .transcript import Segment, Transcript

log = logging.getLogger(__name__)


class LiveSession:
    """Live lecture session: feed audio chunks, emit captions, save transcript on end.

    If STT fails for a chunk, the error is recorded in `last_error` and the session
    continues without captions for that chunk (the lecture is not interrupted).
    """

    def __init__(self, transcriber: Transcriber, output_path=None,
                 on_caption: Optional[Callable[[Segment], None]] = None,
                 slide_terms: Optional[Dict[int, Iterable[str]]] = None):
        self.transcriber = transcriber
        self.output_path = Path(output_path) if output_path else None
        self.on_caption = on_caption
        self.slide_terms = slide_terms  # slide number -> English terms on that slide
        self.transcript = Transcript(language=transcriber.config.language)
        glossary = transcriber.glossary  # load and validate before the session starts
        if glossary is not None:
            self.transcript.glossary = glossary.info
        self.status = "created"
        self.slide: Optional[int] = None
        self.elapsed = 0.0
        self.last_error: Optional[str] = None

    def start(self) -> None:
        self.status = "live"

    def set_slide(self, number: int) -> None:
        self.slide = number

    def feed(self, chunk) -> List[Segment]:
        if self.status != "live":
            raise STTError("Session is not live")
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
        offset = self.elapsed
        self.elapsed += chunk.size / self.transcriber.config.sample_rate
        try:
            segments = self.transcriber.transcribe_chunk(chunk, offset)
            self.last_error = None
        except STTError as exc:
            self.last_error = str(exc)
            log.warning("STT unavailable, continuing without captions: %s", exc)
            return []
        for seg in segments:
            seg.slide = self.slide
        if self.transcript.glossary is not None:
            try:
                segments = self.transcriber.correct(segments, self.slide_terms)
            except Exception as exc:  # never drop captions because of the correction layer
                self.last_error = f"Term correction failed: {exc}"
                log.warning("%s; captions kept uncorrected", self.last_error)
                segments = [replace(s, raw_text=s.text, corrections=[]) for s in segments]
        for seg in segments:
            self.transcript.segments.append(seg)
            if self.on_caption:
                self.on_caption(seg)
        return segments

    def end(self) -> Transcript:
        self.status = "ended"
        if self.output_path:
            self.transcript.save(self.output_path)
        return self.transcript


def record_microphone(session: LiveSession, seconds: float, chunk_seconds: float = 5.0) -> Transcript:
    """Capture from the default microphone in fixed-size chunks (requires sounddevice)."""
    try:
        import sounddevice as sd
    except Exception as exc:
        raise STTError(f"Microphone capture unavailable (sounddevice): {exc}") from exc
    sr = session.transcriber.config.sample_rate
    session.start()
    remaining = seconds
    try:
        while remaining > 0:
            dur = min(chunk_seconds, remaining)
            audio = sd.rec(int(dur * sr), samplerate=sr, channels=1, dtype="float32")
            sd.wait()
            session.feed(audio)
            remaining -= dur
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        session.end()
        raise STTError(f"Microphone error: {exc}") from exc
    return session.end()
