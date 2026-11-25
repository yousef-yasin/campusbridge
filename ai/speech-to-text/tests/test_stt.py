import numpy as np
import pytest

from conftest import FakeModel, write_wav
from stt import (AudioNotFoundError, LiveSession, ModelUnavailableError, Segment, STTConfig,
                 Transcriber, Transcript, TranscriptionError)
from stt.__main__ import main


def test_config_defaults_to_arabic_and_cpu_int8(monkeypatch):
    monkeypatch.setattr("stt.config._detect_device", lambda: "cpu")
    cfg = STTConfig()
    assert cfg.language == "ar"
    assert cfg.resolved() == ("cpu", "int8")
    assert STTConfig(device="cuda").resolved() == ("cuda", "float16")


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("STT_MODEL", "medium")
    monkeypatch.setenv("STT_VAD_FILTER", "false")
    cfg = STTConfig.from_env()
    assert cfg.model == "medium" and cfg.vad_filter is False


def test_transcribe_file_returns_timestamped_segments(tmp_path, fake_model):
    audio = write_wav(tmp_path / "lecture.wav")
    t = Transcriber(STTConfig(), model=fake_model).transcribe_file(audio)
    assert [(s.start, s.end) for s in t.segments] == [(0.0, 2.0), (2.0, 4.5)]
    assert t.segments[0].text == "مرحبا بكم في المحاضرة"
    assert fake_model.calls[0][1]["language"] == "ar"


def test_missing_and_empty_audio(tmp_path, fake_model):
    tr = Transcriber(STTConfig(), model=fake_model)
    with pytest.raises(AudioNotFoundError):
        tr.transcribe_file(tmp_path / "nope.wav")
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    with pytest.raises(AudioNotFoundError):
        tr.transcribe_file(empty)


def test_model_unavailable():
    tr = Transcriber(STTConfig(model="no-such-model-xyz", device="cpu"))
    with pytest.raises(ModelUnavailableError):
        tr.model


def test_transcription_failure_wrapped(tmp_path):
    audio = tmp_path / "bad.wav"
    audio.write_bytes(b"x")
    tr = Transcriber(STTConfig(), model=FakeModel(error=RuntimeError("decode error")))
    with pytest.raises(TranscriptionError):
        tr.transcribe_file(audio)


def test_chunk_offsets_and_empty_chunk(fake_model):
    tr = Transcriber(STTConfig(), model=fake_model)
    segs = tr.transcribe_chunk(np.zeros(16000, dtype=np.float32), offset=10.0)
    assert segs[0].start == 10.0 and segs[1].end == 14.5
    assert tr.transcribe_chunk(np.array([])) == []


def test_save_utf8_and_reload(tmp_path):
    t = Transcript([Segment(0, 3, "الذكاء الاصطناعي", slide=1), Segment(65, 70, "شو يعني خوارزمية؟")])
    path = t.save(tmp_path / "out" / "lecture.txt")
    text = path.read_text(encoding="utf-8")
    assert "[00:00:00 - 00:00:03] [slide 1] الذكاء الاصطناعي" in text
    assert "[00:01:05 - 00:01:10] شو يعني خوارزمية؟" in text
    loaded = Transcript.load(path.with_suffix(".json"))
    assert loaded.full_text == t.full_text and loaded.segments[0].slide == 1


def test_search_ignores_diacritics_and_alef_forms():
    t = Transcript([Segment(0, 1, "مُقَدِّمَة في الإحصاء"), Segment(1, 2, "Data structures")])
    assert len(t.search("مقدمة")) == 1
    assert len(t.search("الاحصاء")) == 1
    assert len(t.search("data")) == 1
    assert t.search("  ") == []


def test_live_session_flow(tmp_path, fake_model):
    captions = []
    out = tmp_path / "live.txt"
    s = LiveSession(Transcriber(STTConfig(), model=fake_model), out, on_caption=captions.append)
    with pytest.raises(Exception):
        s.feed(np.zeros(10))
    s.start()
    s.set_slide(3)
    s.feed(np.zeros(16000 * 5, dtype=np.float32))
    s.set_slide(4)
    second = s.feed(np.zeros(16000 * 5, dtype=np.float32))
    assert second[0].start == 5.0 and second[0].slide == 4
    t = s.end()
    assert s.status == "ended" and len(captions) == 4
    assert out.exists() and out.with_suffix(".json").exists()
    assert t.segments[0].slide == 3


def test_live_session_continues_when_stt_unavailable(tmp_path):
    s = LiveSession(Transcriber(STTConfig(), model=FakeModel(error=RuntimeError("service down"))))
    s.start()
    assert s.feed(np.zeros(16000)) == []
    assert "service down" in s.last_error and s.status == "live"


def test_cli_missing_file_returns_error(tmp_path, capsys):
    assert main(["file", str(tmp_path / "missing.wav")]) == 1
    assert "not found" in capsys.readouterr().err


def test_cli_search(tmp_path, capsys):
    path = Transcript([Segment(0, 1, "مقدمة"), Segment(1, 2, "خاتمة")]).save(tmp_path / "t.txt")
    assert main(["search", str(path.with_suffix(".json")), "خاتمة"]) == 0
    out = capsys.readouterr().out
    assert "خاتمة" in out and "مقدمة" not in out
