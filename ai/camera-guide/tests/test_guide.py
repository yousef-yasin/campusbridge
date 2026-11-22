"""Camera guide on generated frames: one command per case, priority, repeats, auto-capture."""
import json
import statistics
import time

import cv2
import numpy as np
import pytest

from conftest import H, W, page_frame
from camguide import CameraGuide, GuideConfig, analyze, failed_checks, read_capture, say, straighten
from camguide.__main__ import main


def command(frame, **cfg):
    return failed_checks(analyze(frame, GuideConfig(**cfg)), GuideConfig(**cfg))


@pytest.mark.parametrize("name, frame, expected", [
    ("centre", lambda: page_frame(), []),
    ("right", lambda: page_frame(center=(0.66, 0.5), size=0.7), ["move_right"]),
    ("left", lambda: page_frame(center=(0.34, 0.5), size=0.7), ["move_left"]),
    ("high", lambda: page_frame(center=(0.5, 0.32), size=0.7), ["move_up"]),
    ("low", lambda: page_frame(center=(0.5, 0.68), size=0.7), ["move_down"]),
    ("small", lambda: page_frame(size=0.55), ["move_closer"]),
    ("cut", lambda: page_frame(size=1.4), ["move_away"]),
    ("tilted", lambda: page_frame(angle=20, size=0.75), ["tilt"]),
    ("phone tilted", lambda: page_frame(perspective=0.3), ["tilt"]),
    ("shaky", lambda: page_frame(blur=4), ["hold_still"]),
    ("dark", lambda: page_frame(light=0.35), ["too_dark"]),
    ("glare", lambda: page_frame(glare=True), ["glare"]),
    ("empty", lambda: np.full((H, W, 3), 110, np.uint8), ["find_page"]),
])
def test_one_command_per_case(name, frame, expected):
    failed = command(frame())
    assert failed[:1] == expected[:1], (name, failed)


def test_directions_are_phone_moves_and_mirror():
    # page on the right of the frame: the PHONE moves right; a front camera swaps sides
    right = page_frame(center=(0.66, 0.5), size=0.7)
    assert command(right)[0] == "move_right"
    assert command(right, mirrored=True)[0] == "move_left"
    one_side_cut = page_frame(center=(0.78, 0.5), size=0.62)    # goes past the right edge only
    report = analyze(one_side_cut, GuideConfig())
    assert report.cut == ["right"] and failed_checks(report, GuideConfig())[0] == "move_right"


def test_priority_order():
    dark_and_small = page_frame(size=0.42, light=0.35)
    assert command(dark_and_small)[:2] == ["too_dark", "move_closer"]
    shaky_and_right = page_frame(center=(0.68, 0.5), size=0.55, blur=4)
    assert command(shaky_and_right) == ["move_right", "move_closer", "hold_still"]   # every failing check, in order


def test_speed_under_50_ms_per_frame():
    cfg = GuideConfig()
    frame = cv2.resize(page_frame(center=(0.6, 0.5)), (1080, 1920))     # a full-HD phone frame
    analyze(frame, cfg)
    times = [analyze(frame, cfg).ms for _ in range(10)]
    assert statistics.median(times) < 50, times


def test_no_repeat_spam_and_auto_capture_after_one_second():
    guide = CameraGuide(GuideConfig(), language="mixed")
    small = page_frame(size=0.55)
    spoken = [guide.feed(small, t / 10).speak for t in range(0, 50)]          # 5 s at 10 fps
    said = [(t / 10, s) for t, s in enumerate(spoken) if s]
    assert said == [(0.1, "قرّب"), (3.1, "قرّب")]                           # stable 2 frames, then every 3 s
    good = page_frame()
    advices = [guide.feed(good, 5 + t / 10) for t in range(0, 15)]
    assert [a.speak for a in advices if a.speak] == ["ممتاز، اثبت", "تم التصوير"]
    captured = [a for a in advices if a.capture]
    assert len(captured) == 1 and captured[0].t == pytest.approx(6.0)        # after 1.0 s of passing checks
    assert all(a.status == "captured" and not a.capture for a in advices[advices.index(captured[0]) + 1:])
    guide.reset()
    assert guide.feed(small, 9.0).status == "adjusting"


def test_a_short_good_moment_does_not_capture():
    guide = CameraGuide(GuideConfig(hold_seconds=1.0), language="ar")
    frames = [page_frame()] * 6 + [page_frame(center=(0.7, 0.5), size=0.55)] + [page_frame()] * 6
    advices = [guide.feed(f, t / 10) for t, f in enumerate(frames)]
    assert not any(a.capture for a in advices)                              # 0.5 s, break, 0.5 s


def test_english_commands_and_reasons(monkeypatch):
    monkeypatch.setenv("CB_EXPLAIN_LANGUAGE", "en")
    guide = CameraGuide(GuideConfig())
    advice = [guide.feed(page_frame(light=0.35), t / 10) for t in range(3)][-1]
    assert (advice.command, advice.text, advice.reason) == ("too_dark", "The light is too low", "the frame is too dark")
    assert say("move_closer", "ar") == "قرّب" and say("read_failed", "ar") == "ما قدرت أقرأ الورقة، جرّب تصوّر مرة ثانية"


def test_straighten_makes_the_page_upright():
    frame = page_frame(angle=8, size=0.7)
    report = analyze(frame, GuideConfig())
    page = straighten(frame, report.quad)
    again = analyze(cv2.copyMakeBorder(page, 60, 60, 60, 60, cv2.BORDER_CONSTANT, value=(110, 110, 110)), GuideConfig())
    assert abs(again.rotation) < 2.0 and page.shape[0] > page.shape[1]


def test_reading_fails_with_the_retry_message(tmp_path):
    class NoText:
        model = "fake"

        def describe(self, image, mime, prompt, schema):
            return {"blocks": []}
    from cb_shared import use_module
    use_module("document-reader")
    from reader import PageOCR, ReaderConfig
    reader = PageOCR(ReaderConfig.from_env(), engine=NoText(), tesseract=None, language="ar")
    result = read_capture(page_frame(), str(tmp_path / "page.jpg"), "ar", ocr_reader=reader)
    assert not result.ok and result.message == "ما قدرت أقرأ الورقة، جرّب تصوّر مرة ثانية"

    class Reads:
        model = "fake-2"                         # another model: not the cached empty answer

        def describe(self, image, mime, prompt, schema):
            return {"handwritten_page": True, "blocks": [{"kind": "paragraph", "text": "وهنا اجت فكرتنا"}]}
    reader = PageOCR(ReaderConfig.from_env(), engine=Reads(), tesseract=None, language="ar")
    ok = read_capture(page_frame(), str(tmp_path / "page2.jpg"), "ar", ocr_reader=reader)
    assert ok.ok and ok.speech.split("\n\n") == ["نص مستخرج تلقائياً من صورة الصفحة. الورقة مكتوبة بخط اليد.",
                                                 "وهنا اجت فكرتنا"]


def test_cli_on_a_folder_of_frames(tmp_path, capsys):
    folder = tmp_path / "frames"
    folder.mkdir()
    sequence = [page_frame(size=0.55)] * 6 + [page_frame(center=(0.66, 0.5), size=0.7)] * 10 + [page_frame()] * 14
    for i, f in enumerate(sequence):
        cv2.imwrite(str(folder / f"{i:03d}.jpg"), f)
    assert main([str(folder), "--fps", "10", "--out", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert "«قرّب»" in out and "«يمين»" in out and "«تم التصوير»" in out
    assert (tmp_path / "out" / "capture-page.jpg").is_file()
    assert main([str(folder), "--json", "--out", str(tmp_path / "o2")]) == 0
    first = json.loads(capsys.readouterr().out.splitlines()[0])
    assert first["command"] == "move_closer" and first["report"]["found"]


def test_command_voices_are_made_once_and_never_mixed(tmp_path):
    from camguide.commands import COMMANDS
    from camguide.voices import build

    class FakeTTS:
        def __init__(self, fail=()):
            self.fail, self.calls = set(fail), []

        def synthesize(self, text, out):
            self.calls.append(text)
            if text in self.fail:
                raise RuntimeError("Gemini quota or rate limit exceeded (429)")
            path = Path(out).with_suffix(".wav")
            path.write_bytes(b"RIFF")
            return path
    from pathlib import Path
    (tmp_path / "ar").mkdir()
    (tmp_path / "ar" / "move_down.mp3").write_bytes(b"other voice")       # left from a fallback
    index = build("ar", tmp_path, FakeTTS(fail={"نزّل"}))
    assert set(index) == set(COMMANDS) and index["move_down"]["file"] is None
    assert not (tmp_path / "ar" / "move_down.mp3").exists()                   # no clip in another voice
    assert index["move_right"] == {"text": "يمين", "file": "move_right.wav", "error": None}
    assert json.loads((tmp_path / "ar" / "index.json").read_text(encoding="utf-8"))["hold_still"]["text"] == "اثبت"
