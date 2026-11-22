import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError
from .voices import (DEFAULT_GEMINI_VOICE, DEFAULT_VOICE, FALLBACK_VOICE, is_multilingual,
                     resolve_voice)

_ROOT = Path(__file__).resolve().parents[2]   # ai/text-to-speech

ENGINES = ("gemini", "edge", "piper")
# Short on purpose: Google's TTS guide says long style prompts make the voice drift.
DEFAULT_GEMINI_STYLE = ("friendly university lecturer, clear Arabic, English terms and sentences "
                        "in natural English pronunciation")
LANGUAGES = ("auto", "ar", "en")
MIN_SPEED, MAX_SPEED = 0.5, 2.0


@dataclass
class TTSConfig:
    """Settings, overridable through TTS_* environment variables."""
    engine: str = "gemini"                        # gemini / edge (online), piper (local)
    language: str = "auto"                        # auto/ar/en
    fallback_language: str = "ar"                 # auto mode: sentences with no letters
    speed: float = 1.0                            # 0.5 (slow) .. 2.0 (fast)
    # gemini: one voice reads the raw text; the API key comes from GEMINI_API_KEY (env or env_file)
    gemini_model: str = "gemini-3.8-flash-tts"    # or gemini-3.8-flash-lite-tts
    gemini_voice: str = DEFAULT_GEMINI_VOICE      # name or preset alias (see voices.py)
    gemini_style: str = DEFAULT_GEMINI_STYLE      # sent as speech_metadata.style; "" for none
    gemini_max_chars: int = 3000                  # longer text is split at paragraph breaks
    gemini_timeout: int = 180                     # seconds per request
    env_file: str = str(_ROOT / ".env")
    piper_voice_ar: str = "ar_JO-kareem-medium"
    piper_voice_en: str = "en_US-lessac-medium"
    # edge: one Multilingual voice reads everything (name or preset alias, see voices.py).
    # Empty or a single-language voice -> one voice per language (edge_voice_ar / edge_voice_en).
    edge_voice: str = DEFAULT_VOICE
    edge_voice_ar: str = "ar-JO-SanaNeural"
    edge_voice_en: str = "en-US-AriaNeural"
    fallback: bool = True                         # gemini -> edge fallback voice -> Piper
    edge_fallback_voice: str = FALLBACK_VOICE
    voices_dir: str = str(_ROOT / "voices")       # Piper .onnx + .onnx.json files
    cache: bool = True
    cache_dir: str = str(_ROOT / ".tts-cache")
    phrases_file: str = str(_ROOT / "data" / "phrases.json")
    pronunciation_file: str = str(_ROOT / "pronunciation.json")   # word -> spoken form (diacritics)
    pronunciation: bool = True                    # apply it to the text before any engine
    max_chars: int = 250                          # longer sentences are split further
    timeout: int = 30                             # edge network timeout, seconds

    @classmethod
    def from_env(cls) -> "TTSConfig":
        e = os.environ.get
        try:
            return cls(
                engine=e("TTS_ENGINE", cls.engine),
                language=e("TTS_LANGUAGE", cls.language),
                fallback_language=e("TTS_FALLBACK_LANGUAGE", cls.fallback_language),
                speed=float(e("TTS_SPEED", cls.speed)),
                gemini_model=e("TTS_GEMINI_MODEL", cls.gemini_model),
                gemini_voice=e("TTS_GEMINI_VOICE", cls.gemini_voice),
                gemini_style=e("TTS_GEMINI_STYLE", cls.gemini_style),
                gemini_max_chars=int(e("TTS_GEMINI_MAX_CHARS", cls.gemini_max_chars)),
                gemini_timeout=int(e("TTS_GEMINI_TIMEOUT", cls.gemini_timeout)),
                env_file=e("TTS_ENV_FILE", cls.env_file),
                piper_voice_ar=e("TTS_PIPER_VOICE_AR", cls.piper_voice_ar),
                piper_voice_en=e("TTS_PIPER_VOICE_EN", cls.piper_voice_en),
                edge_voice=e("TTS_EDGE_VOICE", cls.edge_voice),
                edge_voice_ar=e("TTS_EDGE_VOICE_AR", cls.edge_voice_ar),
                edge_voice_en=e("TTS_EDGE_VOICE_EN", cls.edge_voice_en),
                fallback=e("TTS_FALLBACK", "1").lower() not in ("0", "false", "no"),
                edge_fallback_voice=e("TTS_EDGE_FALLBACK_VOICE", cls.edge_fallback_voice),
                voices_dir=e("TTS_VOICES_DIR", cls.voices_dir),
                cache=e("TTS_CACHE", "1").lower() not in ("0", "false", "no"),
                cache_dir=e("TTS_CACHE_DIR", cls.cache_dir),
                phrases_file=e("TTS_PHRASES_FILE", cls.phrases_file),
                pronunciation_file=e("TTS_PRONUNCIATION_FILE", cls.pronunciation_file),
                pronunciation=e("TTS_PRONUNCIATION", "1").lower() not in ("0", "false", "no"),
                max_chars=int(e("TTS_MAX_CHARS", cls.max_chars)),
                timeout=int(e("TTS_TIMEOUT", cls.timeout)),
            )
        except ValueError as exc:
            raise ConfigError(f"Invalid TTS_* setting: {exc}") from exc

    def validate(self) -> "TTSConfig":
        self.engine = {"edge-tts": "edge"}.get(self.engine.lower(), self.engine.lower())
        self.language = self.language.lower()
        if self.engine not in ENGINES:
            raise ConfigError(f"Unknown engine '{self.engine}' (use: {', '.join(ENGINES)})")
        if self.language not in LANGUAGES:
            raise ConfigError(f"Unknown language '{self.language}' (use: {', '.join(LANGUAGES)})")
        if self.fallback_language not in ("ar", "en"):
            raise ConfigError("fallback_language must be 'ar' or 'en'")
        self.speed = check_speed(self.speed)
        self.edge_voice = resolve_voice(self.edge_voice)
        self.gemini_voice = resolve_voice(self.gemini_voice, "gemini")
        self.gemini_model = self.gemini_model.strip()
        if not self.gemini_voice or not self.gemini_model:
            raise ConfigError("gemini_voice and gemini_model must not be empty")
        return self

    def set_voice(self, name: str) -> None:
        """Set the voice of the selected engine (Piper voices are per language: not changed)."""
        engine = self.engine.lower()
        if engine == "gemini":
            self.gemini_voice = name
        elif engine.startswith("edge"):
            self.edge_voice = name

    def edge_single_voice(self) -> str:
        """The Multilingual voice that reads all text, or '' when voices are per language."""
        voice = resolve_voice(self.edge_voice)
        return voice if is_multilingual(voice) else ""

    def voice_for(self, lang: str) -> str:
        """Voice name of the selected engine for 'ar' or 'en'."""
        if self.engine == "gemini":
            return resolve_voice(self.gemini_voice, "gemini")
        if self.engine == "edge":
            voice = resolve_voice(self.edge_voice)
            if is_multilingual(voice) or voice.lower().startswith(f"{lang}-"):
                return voice
        return getattr(self, f"{self.engine}_voice_{lang}")


def check_speed(speed) -> float:
    try:
        speed = float(speed)
    except (TypeError, ValueError):
        raise ConfigError(f"Speed must be a number, got {speed!r}") from None
    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise ConfigError(f"Speed {speed} out of range ({MIN_SPEED} to {MAX_SPEED})")
    return speed
