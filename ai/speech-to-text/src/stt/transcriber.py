import logging
import threading
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np

from .config import STTConfig
from .errors import AudioNotFoundError, ModelUnavailableError, TranscriptionError
from .transcript import Segment, Transcript

log = logging.getLogger(__name__)

# Single shared slot: Transcribers using the same model share one instance, and loading a
# different model releases the previous one first, so two models are not held at once.
_shared = {"key": None, "model": None}
_lock = threading.Lock()


class Transcriber:
    """Wraps faster-whisper. The model loads lazily on first use."""

    def __init__(self, config: Optional[STTConfig] = None, model=None):
        self.config = config or STTConfig.from_env()
        self._model = model  # injected model (tests); bypasses the shared slot
        self._glossary = None

    @property
    def glossary(self):
        """Approved glossary from config.glossary_path (loaded once), or None when disabled."""
        if self.config.glossary_path and self._glossary is None:
            from .glossary import load_glossary
            self._glossary = load_glossary(self.config.glossary_path)
        return self._glossary

    def correct(self, segments: List[Segment],
                slide_terms: Optional[Dict[int, Iterable[str]]] = None) -> List[Segment]:
        """Apply glossary term correction; returns segments unchanged when disabled."""
        if self.glossary is None:
            return segments
        from .termfix import correct_segments
        return correct_segments(segments, self.glossary, slide_terms)

    @property
    def model(self):
        if self._model is not None:
            return self._model
        device, compute = self.config.resolved()
        key = (self.config.model, device, compute)
        with _lock:
            if _shared["key"] != key:
                _shared["key"] = _shared["model"] = None
                try:
                    from faster_whisper import WhisperModel
                    log.info("Loading model %s on %s (%s)", self.config.model, device, compute)
                    _shared["model"] = WhisperModel(self.config.model, device=device,
                                                    compute_type=compute)
                except Exception as exc:
                    raise ModelUnavailableError(
                        f"Cannot load STT model '{self.config.model}': {exc}") from exc
                _shared["key"] = key
            return _shared["model"]

    def _code_switching(self) -> bool:
        return self.config.code_switching and self.config.language not in (None, "en")

    def _run(self, audio, offset: float = 0.0) -> List[Segment]:
        model = self.model
        try:
            if self._code_switching() and isinstance(audio, str):
                from faster_whisper import decode_audio
                audio = decode_audio(audio, sampling_rate=self.config.sample_rate)
            segments, _ = model.transcribe(
                audio,
                language=self.config.language,
                beam_size=self.config.beam_size,
                vad_filter=self.config.vad_filter,
            )
            result = [Segment(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]
            if self._code_switching():
                from .codeswitch import refine
                result = refine(model, audio, result, self.config.language, self.config.beam_size)
            for s in result:
                s.start += offset
                s.end += offset
            return result
        except Exception as exc:
            raise TranscriptionError(f"Transcription failed: {exc}") from exc

    def transcribe_file(self, path) -> Transcript:
        path = Path(path)
        if not path.is_file():
            raise AudioNotFoundError(f"Audio file not found: {path}")
        if path.stat().st_size == 0:
            raise AudioNotFoundError(f"Audio file is empty: {path}")
        glossary = self.glossary  # load (and validate) before transcribing
        transcript = Transcript(self._run(str(path)), self.config.language)
        if glossary is not None:
            transcript.segments = self.correct(transcript.segments)
            transcript.glossary = glossary.info
        return transcript

    def transcribe_chunk(self, audio, offset: float = 0.0) -> List[Segment]:
        """Transcribe mono float32 PCM at config.sample_rate; timestamps shifted by offset."""
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            return []
        return self._run(audio, offset)
