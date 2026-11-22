"""Generated camera frames: a sheet of paper with lines of writing on a table."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

W, H = 720, 1280                      # a portrait phone frame


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    import os
    for k in [k for k in os.environ if k.startswith(("CAMERA_", "READER_")) or
              k in ("GEMINI_API_KEY", "CB_EXPLAIN_LANGUAGE")]:
        monkeypatch.delenv(k)
    for name in ("IMAGES_DIR", "DESCRIPTIONS_DIR", "OCR_DIR"):
        monkeypatch.setenv(f"READER_{name}", str(tmp_path / name.lower()))
    monkeypatch.setenv("READER_ENV_FILE", str(tmp_path / "no.env"))         # never the real key


def page_frame(center=(0.5, 0.5), size=0.9, angle=0.0, light=1.0, blur=0, glare=False, perspective=0.0,
               table=110):
    """A frame with a page of `size` (share of the frame width) at `center` (shares of w, h)."""
    frame = np.full((H, W, 3), table, np.uint8)
    pw, ph = size * W, size * W * 1.6
    cx, cy = center[0] * W, center[1] * H
    rect = np.array([[-pw / 2, -ph / 2], [pw / 2, -ph / 2], [pw / 2, ph / 2], [-pw / 2, ph / 2]], np.float32)
    if perspective:                    # top edge shorter: phone tilted
        rect[0, 0] *= 1 - perspective
        rect[1, 0] *= 1 - perspective
    a = np.radians(angle)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]], np.float32)
    corners = rect @ rot.T + [cx, cy]
    sheet_w, sheet_h = 600, 960
    sheet = np.full((sheet_h, sheet_w, 3), 235, np.uint8)
    for i, y in enumerate(range(55, sheet_h - 25, 40)):
        words = 6 if i % 4 != 3 else 4
        cv2.putText(sheet, " ".join(["word"] * words), (30, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (25, 25, 25), 2)
    src = np.array([[0, 0], [sheet_w, 0], [sheet_w, sheet_h], [0, sheet_h]], np.float32)
    matrix = cv2.getPerspectiveTransform(src, corners.astype(np.float32))
    warped = cv2.warpPerspective(sheet, matrix, (W, H))
    mask = cv2.warpPerspective(np.full((sheet_h, sheet_w), 255, np.uint8), matrix, (W, H)) > 0
    frame[mask] = warped[mask]
    if glare:
        cv2.circle(frame, (int(cx), int(cy)), int(0.18 * W), (255, 255, 255), -1)
    if blur:
        frame = cv2.GaussianBlur(frame, (0, 0), blur)
    if light != 1.0:
        frame = np.clip(frame.astype(np.float32) * light, 0, 255).astype(np.uint8)
    return frame
