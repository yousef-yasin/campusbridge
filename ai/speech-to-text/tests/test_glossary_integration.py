import json
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from glossary_data import demo
from stt import GlossaryError, LiveSession, STTConfig, Transcriber
from stt import __main__ as cli
from stt.glossary import seal
from stt.transcript import Transcript

class FakeModel:
    """Self-contained stand-in for faster_whisper.WhisperModel (no other test helpers needed)."""

    def __init__(self, segments=((0.0, 1.0, "مرحبا"),)):
        self.segments = segments
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        return iter(SimpleNamespace(start=s, end=e, text=t) for s, e, t in self.segments), None


def write_wav(path, seconds=1.0):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return path


SEGS = [(0.0, 2.0, "صباح الخير"), (2.0, 6.5, "لكي تابت الالجوريثم  حللنا"),
        (6.5, 9.0, "نستدعي اي بي اي من الداتابيس")]


def _glossary(tmp_path, data=None, name="g.json"):
    p = tmp_path / name
    p.write_text(json.dumps(data or demo(), ensure_ascii=False), encoding="utf-8")
    return str(p)


def _tr(tmp_path, glossary=True, segments=SEGS):
    cfg = STTConfig(glossary_path=_glossary(tmp_path) if glossary else None)
    return Transcriber(cfg, model=FakeModel(segments=segments))


def test_file_transcription_with_glossary(tmp_path):
    t = _tr(tmp_path).transcribe_file(write_wav(tmp_path / "a.wav"))
    assert t.glossary == {"course": "DEMO101", "version": 1, "sha256": demo()["sha256"]}
    assert [(s.start, s.end, s.slide) for s in t.segments] == [(0.0, 2.0, None), (2.0, 6.5, None),
                                                               (6.5, 9.0, None)]
    assert [s.raw_text for s in t.segments] == [s[2] for s in SEGS]
    assert t.segments[0].corrections == []                          # always present when enabled
    assert t.segments[1].text == "لكي تابت الـ algorithm  حللنا"    # whitespace preserved
    # uploaded file: no slide context -> acronym (needs slide evidence) is left unchanged
    assert t.segments[2].text == "نستدعي اي بي اي من الـ database"
    data = json.loads(t.save(tmp_path / "o.txt").with_suffix(".json").read_text(encoding="utf-8"))
    assert data["glossary"]["version"] == 1 and "raw_full_text" in data
    assert all("raw_text" in s and "corrections" in s for s in data["segments"])


def test_file_transcription_disabled_is_unchanged(tmp_path):
    t = _tr(tmp_path, glossary=False).transcribe_file(write_wav(tmp_path / "a.wav"))
    assert t.glossary is None
    assert all(s.raw_text is None and s.corrections is None for s in t.segments)
    data = json.loads(t.save(tmp_path / "o.txt").with_suffix(".json").read_text(encoding="utf-8"))
    assert set(data) == {"language", "full_text", "segments"}
    assert all(set(s) == {"start", "end", "text", "slide"} for s in data["segments"])


def test_tampered_glossary_fails_before_transcription(tmp_path):
    bad = demo()
    bad["terms"][0]["aliases"][0]["ar"] = "الجوريتم"
    model = FakeModel()
    tr = Transcriber(STTConfig(glossary_path=_glossary(tmp_path, bad)), model=model)
    with pytest.raises(GlossaryError, match="integrity"):
        tr.transcribe_file(write_wav(tmp_path / "a.wav"))
    assert model.calls == []
    with pytest.raises(GlossaryError):
        LiveSession(tr)


def test_live_session_uses_slide_evidence_and_keeps_slides(tmp_path):
    captions = []
    s = LiveSession(_tr(tmp_path, segments=[(0.0, 4.0, "نستدعي اي بي اي من الداتابيس")]),
                    tmp_path / "live.txt", on_caption=captions.append, slide_terms={2: ["API"]})
    s.start()
    s.set_slide(1)
    s.feed(np.zeros(16000 * 5, dtype=np.float32))
    s.set_slide(2)
    s.feed(np.zeros(16000 * 5, dtype=np.float32))
    t = s.end()
    assert [c.slide for c in captions] == [1, 2]
    assert captions[0].text == "نستدعي اي بي اي من الـ database"     # slide 1 lacks "API"
    assert captions[1].text == "نستدعي API من الـ database"
    assert [c.start for c in captions] == [0.0, 5.0]                    # timestamps unchanged
    assert all(c.raw_text == "نستدعي اي بي اي من الداتابيس" for c in captions)
    assert t.glossary["course"] == "DEMO101"
    saved = Transcript.load(tmp_path / "live.json")
    assert saved.segments[1].corrections[0]["term"] == "API"


def test_live_session_keeps_captions_if_correction_fails(tmp_path, monkeypatch):
    tr = _tr(tmp_path, segments=[(0.0, 1.0, "الالجوريثم")])
    captions = []
    s = LiveSession(tr, on_caption=captions.append)
    monkeypatch.setattr(tr, "correct", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    s.start()
    s.feed(np.zeros(16000, dtype=np.float32))
    assert captions[0].text == "الالجوريثم" and captions[0].raw_text == "الالجوريثم"
    assert captions[0].corrections == [] and "boom" in s.last_error


def test_saved_transcript_not_changed_by_later_glossary_version(tmp_path, monkeypatch):
    t = _tr(tmp_path).transcribe_file(write_wav(tmp_path / "a.wav"))
    path = t.save(tmp_path / "o.txt").with_suffix(".json")
    before = path.read_bytes()
    v2 = demo(version=2)
    v2["terms"][0]["aliases"] = [{"ar": "الجوريثم", "status": "rejected"}]
    v2 = seal(v2)
    monkeypatch.setenv("STT_GLOSSARY", _glossary(tmp_path, v2, "v2.json"))
    loaded = Transcript.load(path)
    assert loaded.glossary["version"] == 1
    assert loaded.segments[1].text == "لكي تابت الـ algorithm  حللنا"
    loaded.save(tmp_path / "copy.txt")
    assert (tmp_path / "copy.json").read_bytes() == before


def test_cli_glossary_option(tmp_path, monkeypatch, capsys):
    import faster_whisper
    monkeypatch.setattr(faster_whisper, "WhisperModel",
                        lambda *a, **k: FakeModel(segments=[(0.0, 2.0, "الالجوريثم")]))
    audio = write_wav(tmp_path / "a.wav")
    assert cli.main(["--glossary", _glossary(tmp_path), "file", str(audio)]) == 0
    assert "الـ algorithm" in capsys.readouterr().out
    data = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert data["segments"][0]["raw_text"] == "الالجوريثم"

    bad = demo()
    bad["version"] = 9                                                   # edited without resealing
    assert cli.main(["--glossary", _glossary(tmp_path, bad, "bad.json"), "file", str(audio)]) == 1
    assert "integrity" in capsys.readouterr().err
