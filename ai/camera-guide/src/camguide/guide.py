"""The camera guide: frames in, one command out, and the moment to take the photo.

    guide = CameraGuide()
    advice = guide.feed(frame, t)          # t: seconds (camera timestamp)
    if advice.speak: play(advice.speak)    # None when the command should not be repeated yet
    if advice.capture: take_full_resolution_photo()

Rules:
- checks in a fixed order (commands.PRIORITY); the first failing one is THE command;
- a new command must be seen stable_frames frames in a row before it is spoken, there is at
  least min_gap_seconds between two spoken commands, and the same command is not repeated
  before repeat_seconds (so the student is not flooded);
- when every check passes, «ممتاز، اثبت» is said once; if they keep passing for hold_seconds
  (default 1 s), capture is True once and «تم التصوير» is said. Call reset() to start again.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .analyze import FrameReport, analyze
from .commands import PRIORITY, reason, say
from .config import GuideConfig


def language_mode(value: Optional[str] = None) -> str:
    """The shared CB_EXPLAIN_LANGUAGE setting (ai/shared): ar and mixed -> Arabic, en -> English."""
    from cb_shared.explain import explain_language
    return explain_language(value)


@dataclass
class Advice:
    t: float
    status: str                      # "searching", "adjusting", "ready", "captured"
    command: str                     # key in commands.COMMANDS
    text: str                        # the command in the student's language
    reason: str
    speak: Optional[str] = None      # text to say now, or None (repeat suppressed)
    capture: bool = False            # take the full-resolution photo now
    failed: List[str] = field(default_factory=list)     # every failing check, in priority order
    report: Optional[FrameReport] = None

    def to_dict(self) -> Dict:
        return {"t": round(self.t, 3), "status": self.status, "command": self.command, "text": self.text,
                "reason": self.reason, "speak": self.speak, "capture": self.capture, "failed": self.failed,
                "report": self.report.to_dict() if self.report else None}


def failed_checks(r: FrameReport, cfg: GuideConfig) -> List[str]:
    """Every failing check, in priority order."""
    if not r.found:
        return ["find_page"] + (["too_dark"] if r.brightness < cfg.min_brightness else [])
    out = []
    if r.brightness < cfg.min_brightness:
        out.append("too_dark")
    dx, dy = r.offset
    if r.cut:
        one_side = len(r.cut) == 1 and r.area < 0.8
        if one_side:          # the page goes past one side only: move the phone towards it
            out.append({"left": "move_left", "right": "move_right", "top": "move_up", "bottom": "move_down"}[r.cut[0]])
        else:
            out.append("move_away")
    if abs(dx) > cfg.center_tolerance or abs(dy) > cfg.center_tolerance:
        if abs(dx) >= abs(dy):
            out.append("move_right" if dx > 0 else "move_left")
        else:
            out.append("move_down" if dy > 0 else "move_up")
    if r.area < cfg.min_area and not r.cut:
        out.append("move_closer")
    if abs(r.rotation) > cfg.max_rotation or r.side_ratio < cfg.min_side_ratio:
        out.append("tilt")
    if r.glare > cfg.max_glare:
        out.append("glare")
    if r.sharpness < cfg.min_sharpness:
        out.append("hold_still")
    order = {k: i for i, k in enumerate(PRIORITY)}
    return sorted(dict.fromkeys(out), key=order.get)


class CameraGuide:
    def __init__(self, config: Optional[GuideConfig] = None, language: Optional[str] = None):
        self.config = config or GuideConfig.from_env()
        self.mode = "en" if language_mode(language) == "en" else "ar"
        self.reset()

    def reset(self) -> None:
        self.captured = False
        self._ok_since: Optional[float] = None
        self._candidate: Optional[str] = None
        self._candidate_count = 0
        self._last_said: Dict[str, float] = {}
        self._last_any: float = -1e9
        self._ready_said = False
        self.last_report: Optional[FrameReport] = None

    def feed(self, frame: np.ndarray, t: float) -> Advice:
        report = analyze(frame, self.config)
        return self.decide(report, t)

    def decide(self, report: FrameReport, t: float) -> Advice:
        self.last_report = report
        cfg = self.config
        if self.captured:
            return self._advice(t, "captured", "captured", report, [], speak=False)
        failed = failed_checks(report, cfg)
        if failed:
            self._ok_since, self._ready_said = None, False
            command = failed[0]
            status = "searching" if command == "find_page" else "adjusting"
            return self._advice(t, status, command, report, failed)
        if self._ok_since is None:
            self._ok_since = t
        if t - self._ok_since >= cfg.hold_seconds:
            self.captured = True
            advice = self._advice(t, "captured", "captured", report, [], force=True)
            advice.capture = True
            return advice
        advice = self._advice(t, "ready", "ready", report, [], speak=not self._ready_said, force=True)
        self._ready_said = self._ready_said or advice.speak is not None
        return advice

    def _advice(self, t, status, command, report, failed, speak=True, force=False) -> Advice:
        text = say(command, self.mode)
        advice = Advice(t, status, command, text, reason(command, self.mode), failed=failed, report=report)
        if command == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate, self._candidate_count = command, 1
        stable = force or self._candidate_count >= self.config.stable_frames
        last = self._last_said.get(command)
        repeat_ok = last is None or t - last >= self.config.repeat_seconds
        gap_ok = force or t - self._last_any >= self.config.min_gap_seconds
        if speak and stable and repeat_ok and gap_ok:
            advice.speak = text
            self._last_said[command] = t
            self._last_any = t
        return advice
