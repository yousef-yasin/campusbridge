import logging
from pathlib import Path
from typing import List, Optional

from .cache import AudioCache
from .config import TTSConfig, check_speed
from .engines import EdgeEngine, Engine, PiperEngine, get_engine
from .errors import (ConfigError, EmptyTextError, EngineUnavailableError, InputNotFoundError,
                     SynthesisError, TTSError)
from .pronunciation import Pronunciations
from .text import Segment, detect_language, prepare, split_paragraphs

log = logging.getLogger(__name__)


class Synthesizer:
    """Turns Arabic/English text into one audio file. The engine loads lazily on first use.

    With config.fallback on, a failure walks the fallback chain:
    gemini (no key, 429 quota, no internet, any failure) -> edge with
    config.edge_fallback_voice -> local Piper;
    edge: chosen voice returned no audio -> config.edge_fallback_voice -> local Piper,
    edge unreachable -> local Piper.
    `fallbacks` lists what the last call used and `fallback_reasons` why.
    """

    def __init__(self, config: Optional[TTSConfig] = None, engine: Optional[Engine] = None,
                 cache: Optional[AudioCache] = None):
        self.config = (config or TTSConfig.from_env()).validate()
        self._engine = engine   # injected engine (tests)
        self.cache = cache or AudioCache(self.config.cache_dir, self.config.cache)
        self.pronunciations = Pronunciations(self.config.pronunciation_file, self.config.pronunciation)
        self.last_error: Optional[str] = None
        self.fallbacks: List[str] = []          # e.g. ["edge:ar-JO-SanaNeural"] or ["piper"]
        self.fallback_reasons: List[str] = []   # the errors that led to the fallback

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = get_engine(self.config)
        return self._engine

    def segments(self, text: str, language: Optional[str] = None,
                 engine: Optional[Engine] = None) -> List[Segment]:
        """The normalized pieces that would be spoken, each with its language.

        The pronunciation dictionary is applied first (place names, scientific terms).
        With a single multilingual voice the whole text is one piece (no language split).
        A raw-text engine (Gemini) gets the text as written, split only at paragraph breaks
        when it is longer than the engine's request limit.
        """
        language = (language or self.config.language).lower()
        if language not in ("auto", "ar", "en"):
            raise ConfigError(f"Unknown language '{language}' (use: auto, ar, en)")
        engine = engine or self.engine
        text = self.pronunciations.apply(text or "")      # spoken form only; the caller's text is unchanged
        if getattr(engine, "raw_text", False):
            return [Segment(detect_language(p, self.config.fallback_language), p)
                    for p in split_paragraphs(text, getattr(engine, "max_chars", 0))]
        single = bool(getattr(engine, "single_voice", ""))
        parts = prepare(text or "", language, self.config.fallback_language,
                        self.config.max_chars, split_languages=not single)
        if single and parts:
            return [Segment(parts[0].lang, " ".join(p.text for p in parts))]
        return parts

    def _speak(self, engine: Engine, text: str, language: Optional[str], speed: float) -> bytes:
        clips = []
        for seg in self.segments(text, language, engine):
            tag = engine.cache_tag() if hasattr(engine, "cache_tag") else ""
            key = self.cache.key(engine.name, engine.voice_for(seg.lang), speed, seg.text, tag)
            clip = self.cache.get(key, engine.ext)
            if clip is None:
                try:
                    clip = engine.synthesize(seg.text, seg.lang, speed)
                except TTSError:
                    raise
                except Exception as exc:
                    raise SynthesisError(f"Synthesis failed: {exc}") from exc
                if not clip:
                    raise SynthesisError(f"Engine returned no audio for: {seg.text[:40]}")
                self.cache.put(key, engine.ext, clip)
            clips.append(clip)
        try:
            return engine.join(clips)
        except TTSError:
            raise
        except Exception as exc:
            raise SynthesisError(f"Could not join audio clips: {exc}") from exc

    def _fallback_chain(self, engine: Engine, error: TTSError):
        """(label, engine factory) pairs to try after the primary engine failed with `error`."""
        if not self.config.fallback or engine.name not in ("gemini", "edge"):
            return
        voice = self.config.edge_fallback_voice
        if engine.name == "gemini":
            try_edge = bool(voice)
        else:   # edge: another voice only helps when the service itself answered
            no_audio = not isinstance(error, EngineUnavailableError)
            try_edge = no_audio and bool(voice) and getattr(engine, "single_voice", "") != voice
        if try_edge:
            yield f"edge:{voice}", lambda: EdgeEngine(self.config, single_voice=voice)
        yield "piper", lambda: PiperEngine(self.config)

    def synthesize(self, text: str, out=None, language: Optional[str] = None,
                   speed: Optional[float] = None) -> Path:
        """Speak text into an audio file and return its path.

        The file extension follows the engine that produced the audio (gemini and piper:
        .wav, edge: .mp3), so it can change when a fallback is used.
        Raises a TTSError subclass on failure; nothing is written in that case.
        """
        self.fallbacks, self.fallback_reasons = [], []
        speed = check_speed(self.config.speed if speed is None else speed)
        engine = self.engine
        if not self.segments(text, language, engine):
            raise EmptyTextError("No speakable text")
        try:
            audio = self._speak(engine, text, language, speed)
        except (ConfigError, EmptyTextError):
            raise
        except TTSError as first:
            errors, audio = [str(first)], None
            for label, factory in self._fallback_chain(engine, first):
                log.warning("TTS fallback -> %s (reason: %s)", label, errors[-1])
                try:
                    candidate = factory()
                    audio = self._speak(candidate, text, language, speed)
                except TTSError as exc:
                    errors.append(f"{label}: {exc}")
                    continue
                engine = candidate
                self.fallbacks.append(label)
                self.fallback_reasons = list(errors)
                break
            if audio is None:
                if len(errors) == 1:
                    raise
                raise type(first)("All engines failed. " + " | ".join(errors)) from first
        out = Path(out or "speech").with_suffix(f".{engine.ext}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(audio)
        return out

    def synthesize_file(self, path, out=None, language: Optional[str] = None,
                        speed: Optional[float] = None) -> Path:
        """Speak a UTF-8 text file; output defaults to the same name with the audio extension."""
        path = Path(path)
        if not path.is_file():
            raise InputNotFoundError(f"Text file not found: {path}")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise InputNotFoundError(f"Text file is not UTF-8: {path}") from exc
        return self.synthesize(text, out or path, language, speed)

    def try_synthesize(self, text: str, out=None, language: Optional[str] = None,
                       speed: Optional[float] = None) -> Optional[Path]:
        """Like synthesize(), but never raises: returns None and sets last_error on failure."""
        try:
            path = self.synthesize(text, out, language, speed)
            self.last_error = None
            return path
        except (TTSError, OSError) as exc:
            self.last_error = str(exc)
            log.warning("TTS unavailable, continuing without audio: %s", exc)
            return None
