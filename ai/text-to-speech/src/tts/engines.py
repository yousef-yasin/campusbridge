"""TTS engines behind one interface: Gemini (online, default), edge-tts (online) and Piper (local)."""
import asyncio
import concurrent.futures
import io
import logging
import threading
import wave
from pathlib import Path
from typing import List

import numpy as np

from .config import TTSConfig
from .errors import (ConfigError, EngineUnavailableError, QuotaExceededError, SynthesisError,
                     TTSError, VoiceNotFoundError)
from .keys import get_key, scrub
from .voices import resolve_voice

log = logging.getLogger(__name__)


class Engine:
    """Common interface. synthesize() returns one audio clip in the engine's own format."""
    name = ""
    ext = "wav"
    single_voice = ""   # set when one multilingual voice reads all text (no language split)
    raw_text = False    # True: text is sent as written (no number expansion, no sentence split)
    max_chars = 0       # raw_text engines: request size limit, split at paragraph breaks

    def __init__(self, config: TTSConfig):
        self.config = config

    def voice_for(self, lang: str) -> str:
        return getattr(self.config, f"{self.name}_voice_{lang}")

    def synthesize(self, text: str, lang: str, speed: float) -> bytes:
        raise NotImplementedError

    def join(self, clips: List[bytes]) -> bytes:
        """Concatenate clips produced by this engine into one playable file."""
        raise NotImplementedError

    def cache_tag(self) -> str:
        """Extra settings that change the audio and so belong in the cache key."""
        return ""


def join_wav(clips: List[bytes]) -> bytes:
    """Concatenate 16-bit mono WAV clips; clips at another sample rate are resampled."""
    if len(clips) == 1:
        return clips[0]
    rate, parts = None, []
    for clip in clips:
        with wave.open(io.BytesIO(clip), "rb") as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1:
                raise SynthesisError("Only 16-bit mono WAV clips can be joined")
            sr = w.getframerate()
            samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        rate = rate or sr
        if sr != rate and samples.size:
            target = np.linspace(0, samples.size - 1, int(round(samples.size * rate / sr)))
            samples = np.interp(target, np.arange(samples.size), samples).astype(np.int16)
        parts.append(samples)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.concatenate(parts).tobytes())
    return out.getvalue()


# Loaded Piper voices, shared by all PiperEngine instances (one ONNX session per model file).
_voices = {}
_lock = threading.Lock()


class PiperEngine(Engine):
    """Local neural TTS. Needs <voice>.onnx and <voice>.onnx.json in config.voices_dir."""
    name = "piper"
    ext = "wav"

    def _voice(self, lang: str):
        name = self.voice_for(lang)
        model = Path(self.config.voices_dir) / f"{name}.onnx"
        with _lock:
            if model not in _voices:
                try:
                    from piper import PiperVoice
                except Exception as exc:
                    raise EngineUnavailableError(
                        f"Piper is not installed (pip install piper-tts): {exc}") from exc
                if not model.is_file() or not Path(f"{model}.json").is_file():
                    raise VoiceNotFoundError(
                        f"Piper voice '{name}' not found in {model.parent}. Download it with: "
                        f"python -m piper.download_voices {name} --data-dir \"{model.parent}\"")
                try:
                    log.info("Loading Piper voice %s", name)
                    _voices[model] = PiperVoice.load(model, download_dir=model.parent)
                except Exception as exc:
                    raise VoiceNotFoundError(f"Cannot load Piper voice '{name}': {exc}") from exc
            return _voices[model]

    def synthesize(self, text: str, lang: str, speed: float) -> bytes:
        voice = self._voice(lang)
        try:
            from piper import SynthesisConfig
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                voice.synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=1.0 / speed))
            return buf.getvalue()
        except Exception as exc:
            raise SynthesisError(f"Piper failed to synthesize: {exc}") from exc

    def join(self, clips: List[bytes]) -> bytes:
        return join_wav(clips)


def _collect_audio(talk) -> bytes:
    """All audio bytes of an edge_tts.Communicate, raising whatever the stream raises.

    edge-tts' own stream_sync() blocks forever when the stream fails (unknown voice,
    no internet), so the async stream is run here in a worker thread instead.
    """
    async def collect() -> bytes:
        return b"".join([c["data"] async for c in talk.stream() if c["type"] == "audio"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, collect()).result()


class EdgeEngine(Engine):
    """Online Microsoft Edge neural voices via edge-tts, an unofficial client of the Edge
    read-aloud service. Text is sent to Microsoft; there is no service guarantee."""
    name = "edge"
    ext = "mp3"

    def __init__(self, config: TTSConfig, single_voice: str = ""):
        """single_voice forces one voice for all text; default: config.edge_voice if Multilingual."""
        super().__init__(config)
        self.single_voice = resolve_voice(single_voice) or config.edge_single_voice()

    def voice_for(self, lang: str) -> str:
        if self.single_voice:
            return self.single_voice
        voice = resolve_voice(self.config.edge_voice)
        if voice.lower().startswith(f"{lang}-"):
            return voice
        return getattr(self.config, f"edge_voice_{lang}")

    def synthesize(self, text: str, lang: str, speed: float) -> bytes:
        try:
            import edge_tts
        except Exception as exc:
            raise EngineUnavailableError(
                f"edge-tts is not installed (pip install edge-tts): {exc}") from exc
        voice = self.voice_for(lang)
        try:
            talk = edge_tts.Communicate(
                text, voice, rate=f"{round((speed - 1) * 100):+d}%",
                connect_timeout=self.config.timeout, receive_timeout=self.config.timeout)
            audio = _collect_audio(talk)
        except Exception as exc:
            if isinstance(exc, (OSError, TimeoutError)) or type(exc).__module__.startswith("aiohttp"):
                raise EngineUnavailableError(
                    f"edge-tts service unreachable (internet required): {exc}") from exc
            raise SynthesisError(f"edge-tts failed with voice '{voice}': {exc}") from exc
        if not audio:
            raise SynthesisError(f"edge-tts returned no audio for voice '{voice}'")
        return audio

    def join(self, clips: List[bytes]) -> bytes:
        # All edge voices return the same MP3 stream format, so frames can be appended.
        return b"".join(clips)


def pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    """Wrap headerless 16-bit mono PCM in a WAV container."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


class GeminiEngine(Engine):
    """Gemini TTS (Google, online). One voice reads the raw text; the model detects the language.

    The text is sent to Google's servers. The API key is read from GEMINI_API_KEY (process
    environment, else config.env_file) at request time and is never stored, logged or printed.
    """
    name = "gemini"
    ext = "wav"
    raw_text = True

    def __init__(self, config: TTSConfig, client=None):
        super().__init__(config)
        self.single_voice = resolve_voice(config.gemini_voice, "gemini")
        self.max_chars = config.gemini_max_chars
        self._client = client   # injected client (tests)

    def voice_for(self, lang: str) -> str:
        return self.single_voice

    def cache_tag(self) -> str:
        return f"{self.config.gemini_model}|{self.config.gemini_style}"

    def style_for(self, speed: float) -> str:
        """Style text for the request. Gemini has no speed number, so pace goes in the style."""
        pace = "speaking slowly" if speed < 0.9 else "speaking rapidly" if speed > 1.1 else ""
        return ", ".join(part for part in (self.config.gemini_style.strip(), pace) if part)

    def _get_client(self, key: str):
        if self._client is not None:
            return self._client
        try:
            from google import genai
            from google.genai import types
        except Exception as exc:
            raise EngineUnavailableError(
                f"google-genai is not installed (pip install google-genai): {exc}") from exc
        if not key:
            raise EngineUnavailableError(
                f"GEMINI_API_KEY is not set (put it in {self.config.env_file})")
        # Gemini 3.8 TTS models need the v1beta API; the SDK timeout is in milliseconds.
        return genai.Client(api_key=key, http_options=types.HttpOptions(
            api_version="v1beta", timeout=self.config.gemini_timeout * 1000))

    def _request(self, client, text: str, style: str):
        from google.genai import types
        part = types.Part(text=text)
        if style:
            part.speech_metadata = types.SpeechMetadata(style=style)
        return client.models.generate_content(
            model=self.config.gemini_model,
            contents=[types.Content(role="user", parts=[part])],
            config=types.GenerateContentConfig(
                response_modalities=["audio"],
                speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.single_voice))),
            ),
        )

    def synthesize(self, text: str, lang: str, speed: float) -> bytes:
        key = get_key("GEMINI_API_KEY", self.config.env_file)
        client = self._get_client(key)
        try:
            response = self._request(client, text, self.style_for(speed))
            audio, mime = b"", ""
            for candidate in getattr(response, "candidates", None) or []:
                for part in getattr(getattr(candidate, "content", None), "parts", None) or []:
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and inline.data:
                        audio += inline.data
                        mime = inline.mime_type or mime
        except TTSError:
            raise
        except Exception as exc:
            raise self._error(exc, key) from None   # 'from None': the cause may hold the request
        if not audio:
            raise SynthesisError(f"Gemini returned no audio (voice '{self.single_voice}', "
                                 f"model '{self.config.gemini_model}')")
        if audio[:4] == b"RIFF":
            return audio                             # Gemini 3.8 unary default: complete WAV
        rate = 24000
        for param in mime.split(";"):
            if param.strip().lower().startswith("rate="):
                rate = int(param.split("=", 1)[1] or rate)
        return pcm_to_wav(audio, rate)

    def _error(self, exc: Exception, key: str) -> TTSError:
        code = getattr(exc, "code", None)
        detail = scrub(f"{type(exc).__name__}: {getattr(exc, 'message', None) or exc}", key)[:300]
        if code == 429:
            return QuotaExceededError(f"Gemini quota or rate limit exceeded (429): {detail}")
        if code in (401, 403):
            return EngineUnavailableError(f"Gemini rejected the API key ({code}): {detail}")
        module = type(exc).__module__
        if isinstance(exc, (OSError, TimeoutError)) or module.startswith(("httpx", "httpcore", "aiohttp")):
            return EngineUnavailableError(f"Gemini unreachable (internet required): {detail}")
        if isinstance(code, int) and code >= 500:
            return EngineUnavailableError(f"Gemini service error ({code}): {detail}")
        return SynthesisError(f"Gemini failed (model '{self.config.gemini_model}', "
                              f"voice '{self.single_voice}'): {detail}")

    def join(self, clips: List[bytes]) -> bytes:
        return join_wav(clips)


_ENGINES = {"gemini": GeminiEngine, "piper": PiperEngine, "edge": EdgeEngine}


def get_engine(config: TTSConfig) -> Engine:
    try:
        return _ENGINES[config.engine](config)
    except KeyError:
        raise ConfigError(
            f"Unknown engine '{config.engine}' (use: {', '.join(_ENGINES)})") from None
