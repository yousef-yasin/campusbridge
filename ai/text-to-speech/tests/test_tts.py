import pytest

from conftest import FakeEngine, FakeGeminiClient, make_wav, wav_info
from tts import (PRESET_VOICES, AudioCache, ConfigError, EdgeEngine, EmptyTextError,
                 EngineUnavailableError, GeminiEngine, InputNotFoundError, PhraseBook, PhraseError,
                 PiperEngine, QuotaExceededError, SynthesisError, Synthesizer, TTSConfig,
                 VoiceNotFoundError, get_engine, resolve_voice)
from tts.keys import get_key, read_env_file, scrub
from tts.text import split_paragraphs
from tts.__main__ import main
from tts.engines import join_wav
from tts.phrases import DEFAULT_PHRASES


# --- config -------------------------------------------------------------------------------

def test_config_defaults():
    cfg = TTSConfig().validate()
    assert (cfg.engine, cfg.language, cfg.fallback_language, cfg.speed) == ("gemini", "auto", "ar", 1.0)
    assert (cfg.gemini_model, cfg.gemini_voice) == ("gemini-3.8-flash-tts", "Nika")
    assert "university lecturer" in cfg.gemini_style and "English" in cfg.gemini_style
    assert cfg.voice_for("ar") == cfg.voice_for("en") == "Nika"
    assert cfg.fallback is True and cfg.edge_fallback_voice == "ar-JO-SanaNeural"
    assert "api_key" not in repr(cfg).lower()                 # the key is never part of the config
    cfg = TTSConfig(engine="edge").validate()
    assert cfg.edge_single_voice() == "en-AU-WilliamMultilingualNeural"
    assert cfg.voice_for("ar") == cfg.voice_for("en") == "en-AU-WilliamMultilingualNeural"
    piper = TTSConfig(engine="piper").validate()
    assert piper.voice_for("ar") == "ar_JO-kareem-medium" and piper.voice_for("en") == "en_US-lessac-medium"


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("TTS_ENGINE", "edge-tts")
    monkeypatch.setenv("TTS_LANGUAGE", "EN")
    monkeypatch.setenv("TTS_SPEED", "1.5")
    monkeypatch.setenv("TTS_CACHE", "false")
    monkeypatch.setenv("TTS_EDGE_VOICE", "Emma")
    monkeypatch.setenv("TTS_FALLBACK", "0")
    cfg = TTSConfig.from_env().validate()
    assert (cfg.engine, cfg.language, cfg.speed, cfg.cache) == ("edge", "en", 1.5, False)
    assert cfg.edge_voice == "en-US-EmmaMultilingualNeural" and cfg.fallback is False


def test_config_gemini_from_env_and_set_voice(monkeypatch):
    monkeypatch.setenv("TTS_GEMINI_MODEL", "gemini-3.8-flash-lite-tts")
    monkeypatch.setenv("TTS_GEMINI_VOICE", "male")
    monkeypatch.setenv("TTS_GEMINI_STYLE", "calm")
    monkeypatch.setenv("TTS_GEMINI_MAX_CHARS", "500")
    cfg = TTSConfig.from_env().validate()
    assert (cfg.gemini_model, cfg.gemini_voice, cfg.gemini_style, cfg.gemini_max_chars) == (
        "gemini-3.8-flash-lite-tts", "Finn", "calm", 500)
    cfg.set_voice("nika")
    assert cfg.validate().gemini_voice == "Nika" and cfg.edge_voice == "en-AU-WilliamMultilingualNeural"
    cfg.engine = "edge"
    cfg.set_voice("emma")
    assert cfg.validate().edge_voice == "en-US-EmmaMultilingualNeural" and cfg.gemini_voice == "Nika"
    with pytest.raises(ConfigError):
        TTSConfig(gemini_model=" ").validate()


def test_config_edge_voice_per_language(monkeypatch):
    monkeypatch.setenv("TTS_ENGINE", "edge")
    monkeypatch.setenv("TTS_EDGE_VOICE", "")
    monkeypatch.setenv("TTS_EDGE_VOICE_AR", "ar-JO-TaimNeural")
    cfg = TTSConfig.from_env().validate()
    assert cfg.edge_single_voice() == ""
    assert cfg.voice_for("ar") == "ar-JO-TaimNeural" and cfg.voice_for("en") == "en-US-AriaNeural"
    one_language = TTSConfig(engine="edge", edge_voice="ar-EG-SalmaNeural").validate()
    assert one_language.edge_single_voice() == ""
    assert one_language.voice_for("ar") == "ar-EG-SalmaNeural"
    assert one_language.voice_for("en") == "en-US-AriaNeural"


def test_preset_voices_and_aliases():
    assert [v.name for v in PRESET_VOICES if v.engine == "edge"] == [
        "en-AU-WilliamMultilingualNeural", "en-US-EmmaMultilingualNeural",
        "en-US-BrianMultilingualNeural", "fr-FR-RemyMultilingualNeural",
        "fr-FR-VivienneMultilingualNeural"]
    assert [(v.alias, v.gender) for v in PRESET_VOICES if v.default and v.engine == "edge"] == [
        ("william", "male"), ("emma", "female")]
    assert [(v.name, v.gender, v.default) for v in PRESET_VOICES if v.engine == "gemini"] == [
        ("Nika", "female", True), ("Finn", "male", True)]
    assert resolve_voice("female", "gemini") == resolve_voice("NIKA", "gemini") == "Nika"
    assert resolve_voice("male", "gemini") == "Finn" and resolve_voice("Kore", "gemini") == "Kore"
    assert resolve_voice("emma", "gemini") == "emma"          # edge alias is not a Gemini voice
    assert resolve_voice("male") == resolve_voice("William") == "en-AU-WilliamMultilingualNeural"
    assert resolve_voice("female") == resolve_voice(" emma ") == "en-US-EmmaMultilingualNeural"
    assert resolve_voice("vivienne") == "fr-FR-VivienneMultilingualNeural"
    assert resolve_voice("ar-JO-TaimNeural") == "ar-JO-TaimNeural" and resolve_voice("") == ""


@pytest.mark.parametrize("kwargs", [{"engine": "espeak"}, {"language": "fr"}, {"speed": 3.0},
                                    {"speed": 0.1}, {"fallback_language": "auto"}])
def test_config_rejects_invalid_values(kwargs):
    with pytest.raises(ConfigError):
        TTSConfig(**kwargs).validate()


def test_config_bad_env_number(monkeypatch):
    monkeypatch.setenv("TTS_SPEED", "fast")
    with pytest.raises(ConfigError):
        TTSConfig.from_env()


# --- engines ------------------------------------------------------------------------------

def test_engine_is_selected_from_config(cfg):
    gemini = get_engine(cfg)
    assert isinstance(gemini, GeminiEngine) and gemini.ext == "wav" and gemini.raw_text
    assert gemini.single_voice == gemini.voice_for("ar") == gemini.voice_for("en") == "Nika"
    cfg.engine = "edge"
    edge = get_engine(cfg)
    assert isinstance(edge, EdgeEngine) and edge.ext == "mp3" and not edge.raw_text
    assert edge.single_voice == "en-AU-WilliamMultilingualNeural"
    assert edge.voice_for("ar") == edge.voice_for("en") == "en-AU-WilliamMultilingualNeural"
    cfg.edge_voice = ""
    split = get_engine(cfg)
    assert split.single_voice == ""
    assert split.voice_for("ar") == "ar-JO-SanaNeural" and split.voice_for("en") == "en-US-AriaNeural"
    forced = EdgeEngine(cfg, single_voice="ar-JO-SanaNeural")
    assert forced.single_voice == forced.voice_for("en") == "ar-JO-SanaNeural"
    cfg.engine = "piper"
    piper = get_engine(cfg)
    assert isinstance(piper, PiperEngine) and piper.single_voice == "" and piper.ext == "wav"


def test_piper_missing_voice_is_a_clear_error(cfg):
    with pytest.raises(VoiceNotFoundError) as err:
        PiperEngine(cfg).synthesize("مرحبا", "ar", 1.0)
    assert "ar_JO-kareem-medium" in str(err.value) and "download_voices" in str(err.value)


def test_edge_network_failure_is_engine_unavailable(cfg, monkeypatch):
    import edge_tts

    class Offline:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def stream(self):
            raise OSError("network down")
            yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(edge_tts, "Communicate", Offline)
    cfg.engine = "edge"
    with pytest.raises(EngineUnavailableError):
        EdgeEngine(cfg).synthesize("مرحبا", "ar", 1.0)


def test_edge_speed_becomes_rate_and_audio_chunks_are_joined(cfg, monkeypatch):
    import edge_tts
    seen = {}

    class Talk:
        def __init__(self, text, voice, **kwargs):
            seen.update(text=text, voice=voice, **kwargs)

        async def stream(self):
            for chunk in ({"type": "audio", "data": b"AB"}, {"type": "SentenceBoundary"},
                          {"type": "audio", "data": b"CD"}):
                yield chunk

    monkeypatch.setattr(edge_tts, "Communicate", Talk)
    assert EdgeEngine(cfg).synthesize("مرحبا Hello", "ar", 1.0) == b"ABCD"
    assert seen["voice"] == "en-AU-WilliamMultilingualNeural" and seen["text"] == "مرحبا Hello"
    cfg.edge_voice = ""
    engine = EdgeEngine(cfg)
    assert engine.synthesize("Hello", "en", 1.25) == b"ABCD"
    assert seen["voice"] == "en-US-AriaNeural" and seen["rate"] == "+25%"
    engine.synthesize("مرحبا", "ar", 0.8)
    assert seen["voice"] == "ar-JO-SanaNeural" and seen["rate"] == "-20%"
    assert engine.join([b"AB", b"CD"]) == b"ABCD"


def test_join_wav_resamples_to_first_clip_rate():
    rate, frames = wav_info(join_wav([make_wav(0.1, 22050), make_wav(0.1, 16000)]))
    assert rate == 22050 and frames == 2205 * 2
    one = make_wav(0.1)
    assert join_wav([one]) == one


# --- synthesizer --------------------------------------------------------------------------

def test_synthesize_arabic_writes_audio_file(cfg, fake_engine, tmp_path):
    out = Synthesizer(cfg, engine=fake_engine).synthesize("مرحبا بكم. اليوم 3 محاضرات.",
                                                          tmp_path / "out" / "hello.mp3")
    assert out == tmp_path / "out" / "hello.wav"       # extension follows the engine
    assert wav_info(out.read_bytes()) == (16000, 3200)
    assert fake_engine.calls == [("مرحبا بكم.", "ar", 1.0), ("اليوم ثلاثة محاضرات.", "ar", 1.0)]


def test_auto_language_uses_a_voice_per_part(cfg, tmp_path):
    engine = FakeEngine(rates={"ar": 22050, "en": 16000})
    out = Synthesizer(cfg, engine=engine).synthesize("نستخدم Python اليوم. Thank you.",
                                                     tmp_path / "mixed")
    assert [(lang, text) for text, lang, _ in engine.calls] == [
        ("ar", "نستخدم"), ("en", "Python"), ("ar", "اليوم."), ("en", "Thank you.")]
    assert wav_info(out.read_bytes()) == (22050, 2205 * 4)


def test_manual_language_overrides_detection(cfg, fake_engine, tmp_path):
    s = Synthesizer(cfg, engine=fake_engine)
    s.synthesize("نستخدم Python اليوم", tmp_path / "a", language="ar")
    s.synthesize("We have 2 exams", tmp_path / "b", language="en")
    assert fake_engine.calls == [("نستخدم Python اليوم", "ar", 1.0), ("We have two exams", "en", 1.0)]
    with pytest.raises(ConfigError):
        s.synthesize("نص", tmp_path / "c", language="fr")


def test_speed_is_passed_to_engine_and_validated(cfg, fake_engine, tmp_path):
    cfg.speed = 1.5
    s = Synthesizer(cfg, engine=fake_engine)
    s.synthesize("مرحبا", tmp_path / "a")
    s.synthesize("مرحبا", tmp_path / "b", speed=0.75)
    assert [speed for _, _, speed in fake_engine.calls] == [1.5, 0.75]
    with pytest.raises(ConfigError):
        s.synthesize("مرحبا", tmp_path / "c", speed=5)


def test_cache_is_keyed_by_text_voice_and_speed(cfg, fake_engine, tmp_path):
    s = Synthesizer(cfg, engine=fake_engine)
    s.synthesize("مرحبا", tmp_path / "a")
    s.synthesize("مرحبا", tmp_path / "b")                 # cache hit
    assert len(fake_engine.calls) == 1
    s.synthesize("مرحبا", tmp_path / "c", speed=1.25)     # other speed
    s.synthesize("شكرا", tmp_path / "d")                  # other text
    s.synthesize("Hello", tmp_path / "e")                 # other voice
    assert len(fake_engine.calls) == 4
    assert (tmp_path / "a.wav").read_bytes() == (tmp_path / "b.wav").read_bytes()
    assert AudioCache.key("piper", "v1", 1.0, "x") != AudioCache.key("piper", "v2", 1.0, "x")
    assert AudioCache.key("piper", "v1", 1.0, "x") != AudioCache.key("edge", "v1", 1.0, "x")
    assert s.cache.clear() == 4


def test_cache_can_be_disabled(cfg, fake_engine, tmp_path):
    cfg.cache = False
    s = Synthesizer(cfg, engine=fake_engine)
    s.synthesize("مرحبا", tmp_path / "a")
    s.synthesize("مرحبا", tmp_path / "b")
    assert len(fake_engine.calls) == 2 and not (tmp_path / "cache").exists()


def test_empty_text_and_missing_file(cfg, fake_engine, tmp_path):
    s = Synthesizer(cfg, engine=fake_engine)
    for text in ("", "   ", "... ؟!"):
        with pytest.raises(EmptyTextError):
            s.synthesize(text, tmp_path / "x")
    with pytest.raises(InputNotFoundError):
        s.synthesize_file(tmp_path / "nope.txt")
    assert fake_engine.calls == []


def test_synthesize_file_reads_utf8_and_names_output(cfg, fake_engine, tmp_path):
    src = tmp_path / "notes.txt"
    src.write_text("﻿السطر الأول\nSecond line", encoding="utf-8")
    out = Synthesizer(cfg, engine=fake_engine).synthesize_file(src)
    assert out == tmp_path / "notes.wav" and out.is_file()
    assert [(lang, text) for text, lang, _ in fake_engine.calls] == [("ar", "السطر الأول"),
                                                                     ("en", "Second line")]


def test_engine_failure_is_wrapped_and_writes_nothing(cfg, tmp_path):
    s = Synthesizer(cfg, engine=FakeEngine(error=RuntimeError("onnx crashed")))
    with pytest.raises(SynthesisError):
        s.synthesize("مرحبا", tmp_path / "x")
    assert not (tmp_path / "x.wav").exists() and not (tmp_path / "cache").exists()


def test_try_synthesize_never_raises(cfg, tmp_path):
    s = Synthesizer(cfg, engine=FakeEngine(error=EngineUnavailableError("offline")))
    assert s.try_synthesize("مرحبا", tmp_path / "x") is None
    assert s.last_error == "offline"
    ok = Synthesizer(cfg, engine=FakeEngine())
    assert ok.try_synthesize("مرحبا", tmp_path / "y") == tmp_path / "y.wav" and ok.last_error is None


# --- API key handling -------------------------------------------------------------------------

def test_env_file_parsing_and_key_lookup(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('\ufeff# comment\n\nGEMINI_API_KEY = "file-key-123" \nexport OTHER=\'x\'\nBROKEN\n',
                   encoding="utf-8")
    assert read_env_file(env) == {"GEMINI_API_KEY": "file-key-123", "OTHER": "x"}
    assert read_env_file(tmp_path / "missing.env") == {}
    assert get_key("GEMINI_API_KEY", env) == "file-key-123"
    monkeypatch.setenv("GEMINI_API_KEY", " env-key ")
    assert get_key("GEMINI_API_KEY", env) == "env-key"          # environment wins over the file
    env.write_text("GEMINI_API_KEY=\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY")
    assert get_key("GEMINI_API_KEY", env) == ""
    assert scrub("bad key abc123 rejected", "abc123", "") == "bad key *** rejected"


# --- Gemini engine ----------------------------------------------------------------------------

RAW = "عندنا 3 مواضيع عن machine learning ودقة 92.5%. The quiz has 15 questions."


def test_gemini_sends_raw_text_with_voice_model_and_style(cfg):
    client = FakeGeminiClient()
    audio = GeminiEngine(cfg, client=client).synthesize(RAW, "ar", 1.0)
    assert audio == client.data and wav_info(audio)[0] == 24000        # WAV is returned as is
    assert client.requests == [{
        "model": "gemini-3.8-flash-tts", "text": RAW, "style": cfg.gemini_style, "voice": "Nika",
        "modalities": ["audio"]}]


def test_gemini_settings_are_configurable(cfg):
    cfg.gemini_model, cfg.gemini_voice, cfg.gemini_style = "gemini-3.8-flash-lite-tts", "finn", ""
    client = FakeGeminiClient()
    engine = GeminiEngine(cfg.validate(), client=client)
    engine.synthesize("Hello", "en", 1.0)
    engine.synthesize("Hello", "en", 0.7)
    engine.synthesize("Hello", "en", 1.5)
    assert [(r["model"], r["voice"], r["style"]) for r in client.requests] == [
        ("gemini-3.8-flash-lite-tts", "Finn", None),
        ("gemini-3.8-flash-lite-tts", "Finn", "speaking slowly"),
        ("gemini-3.8-flash-lite-tts", "Finn", "speaking rapidly")]
    cfg.gemini_style = "calm"
    assert GeminiEngine(cfg, client=client).style_for(0.7) == "calm, speaking slowly"


def test_gemini_wraps_headerless_pcm_in_wav(cfg):
    client = FakeGeminiClient(data=b"\x01\x00" * 1600, mime="audio/L16;codec=pcm;rate=16000")
    assert wav_info(GeminiEngine(cfg, client=client).synthesize("Hello", "en", 1.0)) == (16000, 1600)


class ApiError(Exception):
    def __init__(self, code, message):
        super().__init__(f"{code} {message}")
        self.code, self.message = code, message


@pytest.mark.parametrize("error, expected", [
    (ApiError(429, "RESOURCE_EXHAUSTED: quota exceeded"), QuotaExceededError),
    (ApiError(403, "PERMISSION_DENIED"), EngineUnavailableError),
    (ApiError(503, "UNAVAILABLE"), EngineUnavailableError),
    (OSError("getaddrinfo failed"), EngineUnavailableError),
    (ApiError(400, "INVALID_ARGUMENT: unknown voice"), SynthesisError),
])
def test_gemini_errors_are_mapped(cfg, error, expected):
    with pytest.raises(expected):
        GeminiEngine(cfg, client=FakeGeminiClient(error=error)).synthesize("Hello", "en", 1.0)


def test_gemini_no_audio_is_synthesis_error(cfg):
    with pytest.raises(SynthesisError, match="returned no audio"):
        GeminiEngine(cfg, client=FakeGeminiClient(data=b"")).synthesize("Hello", "en", 1.0)


def test_gemini_missing_key_is_unavailable_without_calling_google(cfg):
    with pytest.raises(EngineUnavailableError, match="GEMINI_API_KEY is not set"):
        GeminiEngine(cfg).synthesize("Hello", "en", 1.0)    # genai.Client is blocked in tests


def test_gemini_key_never_appears_in_errors_or_logs(cfg, tmp_path, monkeypatch, caplog, chain):
    secret = "FAKE-TEST-KEY-NOT-REAL"
    (tmp_path / "test.env").write_text(f"GEMINI_API_KEY={secret}\n", encoding="utf-8")
    client = FakeGeminiClient(error=ApiError(400, f"API key not valid: {secret}"))
    with pytest.raises(SynthesisError) as err:
        GeminiEngine(cfg, client=client).synthesize("Hello", "en", 1.0)
    assert secret not in str(err.value) and "***" in str(err.value) and err.value.__cause__ is None
    s = Synthesizer(cfg, engine=GeminiEngine(cfg, client=client))
    with caplog.at_level("DEBUG"):
        s.synthesize("Hello", tmp_path / "x")
    assert s.fallbacks == ["edge:ar-JO-SanaNeural"]
    assert secret not in caplog.text and secret not in " ".join(s.fallback_reasons)
    assert secret not in repr(cfg) and secret not in repr(s.config)


def test_gemini_text_is_raw_and_cached_by_model_voice_and_style(cfg, tmp_path):
    client = FakeGeminiClient()
    s = Synthesizer(cfg, engine=GeminiEngine(cfg, client=client))
    assert [seg.text for seg in s.segments("  " + RAW + "\n")] == [RAW]     # no split, no numbers
    s.synthesize(RAW, tmp_path / "a")
    s.synthesize(RAW, tmp_path / "b")
    assert len(client.requests) == 1                                      # cache hit
    for change in ({"gemini_style": "calm"}, {"gemini_model": "gemini-3.8-flash-lite-tts"},
                   {"gemini_voice": "Finn"}):
        for name, value in change.items():
            setattr(cfg, name, value)
        Synthesizer(cfg, engine=GeminiEngine(cfg, client=client)).synthesize(RAW, tmp_path / "c")
    assert len(client.requests) == 4                                      # each setting is in the key
    Synthesizer(cfg, engine=GeminiEngine(cfg, client=client)).synthesize(RAW, tmp_path / "d")
    assert len(client.requests) == 4


def test_split_paragraphs_only_at_paragraph_breaks():
    assert split_paragraphs("  جملة أولى. جملة ثانية.  ", 5) == ["جملة أولى. جملة ثانية."]   # one paragraph
    assert split_paragraphs("... ؟", 100) == [] and split_paragraphs("", 100) == []
    text = "فقرة أولى طويلة.\n\nSecond paragraph here.\n\nفقرة ثالثة.\n\nالرابعة."
    assert split_paragraphs(text, 1000) == [text]
    assert split_paragraphs(text, 40) == ["فقرة أولى طويلة.\n\nSecond paragraph here.",
                                          "فقرة ثالثة.\n\nالرابعة."]
    assert split_paragraphs("سطر أول\nسطر ثاني\nسطر ثالث", 16) == ["سطر أول\nسطر ثاني", "سطر ثالث"]


def test_gemini_long_text_becomes_one_request_per_paragraph_group(cfg, tmp_path):
    cfg.gemini_max_chars = 40
    client = FakeGeminiClient()
    text = "فقرة أولى فيها 3 أرقام.\n\nSecond paragraph, 2 lines.\n\nفقرة ثالثة."
    out = Synthesizer(cfg, engine=GeminiEngine(cfg, client=client)).synthesize(text, tmp_path / "long")
    assert [r["text"] for r in client.requests] == [
        "فقرة أولى فيها 3 أرقام.", "Second paragraph, 2 lines.\n\nفقرة ثالثة."]
    assert wav_info(out.read_bytes()) == (24000, 4800)          # two 0.1 s clips joined


# --- Gemini fallback chain --------------------------------------------------------------------

def test_gemini_quota_falls_back_to_edge_sana_with_reason(cfg, chain, tmp_path, caplog):
    engine = GeminiEngine(cfg, client=FakeGeminiClient(error=ApiError(429, "RESOURCE_EXHAUSTED")))
    s = Synthesizer(cfg, engine=engine)
    with caplog.at_level("WARNING"):
        out = s.synthesize("عندنا 3 مواضيع", tmp_path / "x")
    assert out.is_file() and s.fallbacks == ["edge:ar-JO-SanaNeural"]
    assert chain["requested"] == [("edge", "ar-JO-SanaNeural")]
    assert chain["edge"].calls == [("عندنا ثلاثة مواضيع", "ar", 1.0)]   # edge gets normalized text
    assert "429" in s.fallback_reasons[0] and "TTS fallback -> edge:ar-JO-SanaNeural" in caplog.text
    assert "429" in caplog.text


def test_gemini_missing_key_falls_back(cfg, chain, tmp_path):
    s = Synthesizer(cfg)                                    # real GeminiEngine, empty test.env
    assert isinstance(s.engine, GeminiEngine)
    s.synthesize("مرحبا", tmp_path / "x")
    assert s.fallbacks == ["edge:ar-JO-SanaNeural"] and "GEMINI_API_KEY is not set" in s.fallback_reasons[0]


def test_gemini_offline_goes_through_edge_then_piper(cfg, chain, tmp_path):
    chain["edge"].error = EngineUnavailableError("edge offline too")
    engine = GeminiEngine(cfg, client=FakeGeminiClient(error=OSError("network down")))
    s = Synthesizer(cfg, engine=engine)
    out = s.synthesize("نستخدم Python", tmp_path / "x")
    assert chain["requested"] == [("edge", "ar-JO-SanaNeural"), ("piper", "")]
    assert s.fallbacks == ["piper"] and out.suffix == ".wav"
    assert "unreachable" in s.fallback_reasons[0] and "edge offline too" in s.fallback_reasons[1]


def test_gemini_no_fallback_raises_the_gemini_error(cfg, chain, tmp_path):
    cfg.fallback = False
    engine = GeminiEngine(cfg, client=FakeGeminiClient(error=ApiError(429, "RESOURCE_EXHAUSTED")))
    with pytest.raises(QuotaExceededError):
        Synthesizer(cfg, engine=engine).synthesize("مرحبا", tmp_path / "x")
    assert chain["requested"] == []


# --- single multilingual voice --------------------------------------------------------------

def test_single_voice_gets_whole_text_with_numbers_per_sentence_language(cfg, tmp_path):
    engine = FakeEngine(name="edge", single_voice="en-AU-WilliamMultilingualNeural")
    s = Synthesizer(cfg, engine=engine)
    out = s.synthesize("عندنا 3 مواضيع عن machine learning. The exam has 40 questions. شكراً",
                       tmp_path / "one")
    assert out.is_file() and s.fallbacks == []
    assert [text for text, _, _ in engine.calls] == [
        "عندنا ثلاثة مواضيع عن machine learning. The exam has forty questions. شكراً"]


def test_single_voice_respects_manual_language(cfg, tmp_path):
    engine = FakeEngine(name="edge", single_voice="en-US-EmmaMultilingualNeural")
    Synthesizer(cfg, engine=engine).synthesize("The exam has 40 questions.", tmp_path / "x",
                                               language="ar")
    assert engine.calls[0][0] == "The exam has أربعون questions."


# --- fallback chain -------------------------------------------------------------------------

@pytest.fixture
def chain(monkeypatch):
    """Fake fallback engines; records which ones the Synthesizer asked for."""
    made = {"edge": FakeEngine(name="edge", single_voice="ar-JO-SanaNeural"),
            "piper": FakeEngine(name="piper"), "requested": []}

    def edge(config, single_voice=""):
        made["requested"].append(("edge", single_voice))
        return made["edge"]

    def piper(config):
        made["requested"].append(("piper", ""))
        return made["piper"]

    monkeypatch.setattr("tts.synthesizer.EdgeEngine", edge)
    monkeypatch.setattr("tts.synthesizer.PiperEngine", piper)
    return made


def primary(error):
    return FakeEngine(error=error, name="edge", single_voice="en-AU-WilliamMultilingualNeural")


def test_no_audio_falls_back_to_sana_and_is_recorded(cfg, chain, tmp_path, caplog):
    s = Synthesizer(cfg, engine=primary(SynthesisError("no audio received")))
    with caplog.at_level("WARNING"):
        out = s.synthesize("مرحبا Hello", tmp_path / "x")
    assert out.is_file() and s.fallbacks == ["edge:ar-JO-SanaNeural"]
    assert chain["requested"] == [("edge", "ar-JO-SanaNeural")]
    assert chain["edge"].calls == [("مرحبا Hello", "ar", 1.0)] and chain["piper"].calls == []
    assert "TTS fallback -> edge:ar-JO-SanaNeural" in caplog.text and "no audio received" in caplog.text


def test_no_internet_falls_back_straight_to_piper(cfg, chain, tmp_path):
    s = Synthesizer(cfg, engine=primary(EngineUnavailableError("offline")))
    out = s.synthesize("نستخدم Python اليوم", tmp_path / "x.mp3")
    assert out == tmp_path / "x.wav" and s.fallbacks == ["piper"]      # Piper writes WAV
    assert chain["requested"] == [("piper", "")]
    assert [(lang, text) for text, lang, _ in chain["piper"].calls] == [
        ("ar", "نستخدم"), ("en", "Python"), ("ar", "اليوم")]             # Piper splits by language


def test_sana_failure_continues_to_piper(cfg, chain, tmp_path):
    chain["edge"].error = EngineUnavailableError("offline now")
    s = Synthesizer(cfg, engine=primary(SynthesisError("no audio received")))
    assert s.synthesize("مرحبا", tmp_path / "x").suffix == ".wav"
    assert chain["requested"] == [("edge", "ar-JO-SanaNeural"), ("piper", "")]
    assert s.fallbacks == ["piper"]


def test_all_engines_failing_is_one_clear_error(cfg, chain, tmp_path):
    chain["edge"].error = SynthesisError("sana silent")
    chain["piper"].error = VoiceNotFoundError("no piper voice")
    s = Synthesizer(cfg, engine=primary(SynthesisError("no audio received")))
    with pytest.raises(SynthesisError) as err:
        s.synthesize("مرحبا", tmp_path / "x")
    message = str(err.value)
    assert "All engines failed" in message and "no audio received" in message
    assert "sana silent" in message and "no piper voice" in message
    assert s.fallbacks == [] and list(tmp_path.glob("x.*")) == []
    assert s.try_synthesize("مرحبا", tmp_path / "x") is None and "All engines failed" in s.last_error


def test_fallback_skips_sana_when_it_is_the_failing_voice(cfg, chain, tmp_path):
    engine = FakeEngine(error=SynthesisError("silent"), name="edge", single_voice="ar-JO-SanaNeural")
    s = Synthesizer(cfg, engine=engine)
    s.synthesize("مرحبا", tmp_path / "x")
    assert chain["requested"] == [("piper", "")] and s.fallbacks == ["piper"]


def test_fallback_can_be_disabled_and_piper_has_none(cfg, chain, tmp_path):
    cfg.fallback = False
    with pytest.raises(SynthesisError, match="no audio received"):
        Synthesizer(cfg, engine=primary(SynthesisError("no audio received"))).synthesize("نص", tmp_path / "x")
    cfg.fallback = True
    with pytest.raises(SynthesisError):
        Synthesizer(cfg, engine=FakeEngine(error=SynthesisError("x"))).synthesize("نص", tmp_path / "y")
    assert chain["requested"] == []


def test_fallbacks_reset_on_next_success(cfg, chain, tmp_path):
    engine = primary(SynthesisError("no audio received"))
    s = Synthesizer(cfg, engine=engine)
    s.synthesize("مرحبا", tmp_path / "a")
    assert s.fallbacks == ["edge:ar-JO-SanaNeural"]
    engine.error = None
    s.synthesize("شكرا", tmp_path / "b")
    assert s.fallbacks == []


# --- phrases ------------------------------------------------------------------------------

def test_default_phrases(cfg):
    book = PhraseBook(cfg.phrases_file)
    phrases = book.list()
    assert len(DEFAULT_PHRASES) >= 10 and len(phrases) == len(DEFAULT_PHRASES)
    assert phrases[0].id == "d1" and not phrases[0].custom
    assert book.get("d5").text == "عندي سؤال"


def test_custom_phrase_add_edit_remove_persist(cfg):
    book = PhraseBook(cfg.phrases_file)
    first = book.add("  أين   القاعة؟ ")
    second = book.add("See you tomorrow")
    assert (first.id, first.text, first.custom) == ("c1", "أين القاعة؟", True) and second.id == "c2"
    assert book.update("c1", "أين قاعة 204؟").text == "أين قاعة 204؟"
    book.remove("c2")
    reloaded = PhraseBook(cfg.phrases_file)
    assert [p.id for p in reloaded.list() if p.custom] == ["c1"]
    assert reloaded.get("c1").text == "أين قاعة 204؟"
    assert reloaded.add("جديد").id == "c3"               # ids are not reused


def test_phrase_errors(cfg, tmp_path):
    book = PhraseBook(cfg.phrases_file)
    for call in (lambda: book.add("   "), lambda: book.update("d1", "x"), lambda: book.remove("d1"),
                 lambda: book.update("c9", "x"), lambda: book.remove("c9"), lambda: book.get("zz")):
        with pytest.raises(PhraseError):
            call()
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(PhraseError):
        PhraseBook(broken).list()


# --- CLI ----------------------------------------------------------------------------------

@pytest.fixture
def cli_engine(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr("tts.synthesizer.get_engine", lambda config: engine)
    return engine


def test_cli_say(cli_engine, tmp_path, capsys):
    out = tmp_path / "say.wav"
    assert main(["--speed", "1.2", "--lang", "ar", "say", "مرحبا Python", "-o", str(out)]) == 0
    assert out.is_file() and cli_engine.calls == [("مرحبا Python", "ar", 1.2)]
    assert f"Saved: {out}" in capsys.readouterr().err


def test_cli_file(cli_engine, tmp_path):
    src = tmp_path / "lecture.txt"
    src.write_text("الجملة الأولى. الجملة الثانية.", encoding="utf-8")
    assert main(["file", str(src)]) == 0
    assert (tmp_path / "lecture.wav").is_file() and len(cli_engine.calls) == 2


def test_cli_phrases(cli_engine, tmp_path, capsys):
    assert main(["phrases"]) == 0
    listed = capsys.readouterr().out
    assert "d1\tمرحباً" in listed and len(listed.splitlines()) == len(DEFAULT_PHRASES)
    assert main(["phrases", "add", "أين المكتبة؟"]) == 0
    assert main(["phrases", "edit", "c1", "أين المختبر؟"]) == 0
    assert main(["phrases", "list"]) == 0
    assert "c1\tأين المختبر؟" in capsys.readouterr().out
    out = tmp_path / "p.wav"
    assert main(["phrases", "say", "c1", "-o", str(out)]) == 0 and out.is_file()
    assert main(["phrases", "remove", "c1"]) == 0
    assert main(["phrases", "remove", "c1"]) == 1
    assert "No phrase with id 'c1'" in capsys.readouterr().err


def test_cli_voices_lists_presets(capsys):
    assert main(["voices"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 7
    assert lines[0] == "gemini\tnika\tNika\tdefault female (selected)"
    assert lines[1] == "gemini\tfinn\tFinn\tdefault male"
    assert lines[2] == "edge\twilliam\ten-AU-WilliamMultilingualNeural\tdefault male"
    assert main(["--voice", "finn", "voices"]) == 0
    assert "gemini\tfinn\tFinn\tdefault male (selected)" in capsys.readouterr().out
    assert main(["--engine", "edge", "--voice", "emma", "voices"]) == 0
    assert "edge\temma\ten-US-EmmaMultilingualNeural\tdefault female (selected)" in capsys.readouterr().out


def test_cli_voice_option_and_fallback_report(monkeypatch, tmp_path, capsys):
    seen = {}
    sana = FakeEngine(name="edge", single_voice="ar-JO-SanaNeural")

    def fake_get_engine(config):
        seen["voice"] = config.edge_voice
        return FakeEngine(error=SynthesisError("no audio received"), name="edge",
                          single_voice=config.edge_voice)

    monkeypatch.setattr("tts.synthesizer.get_engine", fake_get_engine)
    monkeypatch.setattr("tts.synthesizer.EdgeEngine", lambda config, single_voice="": sana)
    assert main(["--engine", "edge", "--voice", "female", "say", "مرحبا", "-o", str(tmp_path / "x")]) == 0
    assert seen["voice"] == "en-US-EmmaMultilingualNeural"
    assert "Fallback used: edge:ar-JO-SanaNeural (reason: no audio received)" in capsys.readouterr().err
    assert main(["--engine", "edge", "--no-fallback", "say", "مرحبا", "-o", str(tmp_path / "y")]) == 1
    assert "Error: no audio received" in capsys.readouterr().err


def test_cli_errors_return_1_with_message(cli_engine, tmp_path, capsys):
    assert main(["say", "   "]) == 1
    assert main(["file", str(tmp_path / "missing.txt")]) == 1
    assert main(["--engine", "espeak", "say", "مرحبا"]) == 1
    assert main(["--speed", "9", "say", "مرحبا"]) == 1
    err = capsys.readouterr().err
    assert err.count("Error:") == 4 and "Unknown engine 'espeak'" in err


def test_cli_missing_piper_voice_does_not_crash(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TTS_VOICES_DIR", str(tmp_path / "no-voices"))
    assert main(["--engine", "piper", "say", "مرحبا", "-o", str(tmp_path / "x.wav")]) == 1
    assert "Piper voice 'ar_JO-kareem-medium' not found" in capsys.readouterr().err
