import sys
import types

import pytest

from stt import STTConfig, Transcriber
from stt import __main__ as cli


@pytest.fixture
def loads(monkeypatch):
    """Replace faster_whisper.WhisperModel; record every model name that gets loaded."""
    loaded = []

    class FakeWhisper:
        def __init__(self, name, device, compute_type):
            loaded.append(name)
            self.name = name

        def transcribe(self, audio, **kw):
            return iter([]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisper))
    monkeypatch.setattr("stt.config._detect_device", lambda: "cpu")
    return loaded


def test_defaults_medium_for_files_small_for_live():
    cfg = STTConfig()
    assert cfg.model == "medium" and cfg.live_model == "small"
    assert cfg.for_live().model == "small"
    assert cfg.model == "medium"  # for_live returns a copy


def test_env_overrides_are_independent(monkeypatch):
    monkeypatch.setenv("STT_MODEL", "large-v3")
    cfg = STTConfig.from_env()
    assert (cfg.model, cfg.live_model) == ("large-v3", "small")
    monkeypatch.setenv("STT_LIVE_MODEL", "base")
    cfg = STTConfig.from_env()
    assert (cfg.model, cfg.live_model) == ("large-v3", "base")
    assert cfg.for_live().model == "base"


def test_explicit_model_argument_still_works(loads):
    Transcriber(STTConfig(model="tiny")).model
    assert loads == ["tiny"]


def test_same_model_is_shared_not_reloaded(loads):
    a, b = Transcriber(STTConfig()), Transcriber(STTConfig())
    assert a.model is b.model
    assert loads == ["medium"]


def test_switching_model_replaces_previous(loads):
    from stt import transcriber
    file_tr = Transcriber(STTConfig())
    live_tr = Transcriber(STTConfig().for_live())
    file_tr.model
    live_tr.model
    assert loads == ["medium", "small"]
    assert transcriber._shared["key"][0] == "small"  # only one model held in the slot


def _run_cli(monkeypatch, tmp_path, argv):
    monkeypatch.setattr(cli, "record_microphone", lambda session, *a: session.end())
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    cmd = ["file", str(audio)] if argv[-1] == "file" else ["mic", "-o", str(tmp_path / "m.txt")]
    return cli.main(argv[:-1] + cmd)


@pytest.mark.parametrize("argv,env,expected", [
    (["file"], {}, "medium"),
    (["mic"], {}, "small"),
    (["file"], {"STT_MODEL": "base"}, "base"),
    (["mic"], {"STT_MODEL": "base"}, "small"),
    (["mic"], {"STT_LIVE_MODEL": "tiny"}, "tiny"),
    (["--model", "large-v3", "file"], {}, "large-v3"),
    (["--model", "large-v3", "mic"], {"STT_LIVE_MODEL": "tiny"}, "large-v3"),
])
def test_cli_model_selection(loads, monkeypatch, tmp_path, argv, env, expected):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert _run_cli(monkeypatch, tmp_path, argv) == 0
    assert loads == [expected]
