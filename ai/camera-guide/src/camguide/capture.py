"""After the photo: straighten the page, then read it with document-reader (the OCR path for images).

The photo must be the camera's FULL-RESOLUTION picture, not the small video frame used for
guiding. Its page corners come from the last analysed frame, scaled to the photo's size.
"""
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from .analyze import order_corners
from .commands import say

MARGIN = 0.03          # keep a little paper around the page corners (share of the page size)


def scale_quad(quad: np.ndarray, from_size, to_size) -> np.ndarray:
    """Corners found on a frame of from_size (w, h) moved to a photo of to_size."""
    sx, sy = to_size[0] / from_size[0], to_size[1] / from_size[1]
    return np.asarray(quad, dtype=np.float32) * np.array([sx, sy], dtype=np.float32)


def straighten(image: np.ndarray, quad: np.ndarray, margin: float = MARGIN) -> np.ndarray:
    """The page as an upright rectangle (perspective corrected), with a small margin."""
    q = order_corners(quad)
    center = q.mean(axis=0)
    q = center + (q - center) * (1 + 2 * margin)
    h_img, w_img = image.shape[:2]
    q[:, 0], q[:, 1] = q[:, 0].clip(0, w_img - 1), q[:, 1].clip(0, h_img - 1)
    tl, tr, br, bl = q
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(q.astype(np.float32), target)
    return cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


@dataclass
class ReadResult:
    ok: bool
    image_path: str
    speech: str = ""                 # ready for the narrator / text-to-speech
    text: str = ""                   # the page text (blocks joined)
    message: str = ""                # what to say when it failed (STB-23)
    ocr: dict = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def read_capture(image: np.ndarray, out_path: Optional[str] = None, language: Optional[str] = None,
                 ocr_reader=None) -> ReadResult:
    """Save the straightened page as JPEG and read it (document-reader, phase 4 OCR).

    The page image is sent to Google (Gemini) for OCR; without internet Tesseract is the
    fallback, except for handwriting. If no text comes out, message is «ما قدرت أقرأ الورقة،
    جرّب تصوّر مرة ثانية».
    """
    from cb_shared import use_module
    from .guide import language_mode
    use_module("document-reader")
    from reader import PageOCR, open_document, to_speech_text
    mode = language_mode(language)
    path = Path(out_path) if out_path else Path(tempfile.mkdtemp(prefix="campage-")) / "page.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    failed = say("read_failed", "en" if mode == "en" else "ar")
    try:
        with open_document(path) as doc:
            page = doc.page(1)
            reader = ocr_reader or PageOCR(language=mode)
            warnings = reader.read_pages(doc, [page])
    except Exception as exc:                                  # unreadable file, OCR crash...
        return ReadResult(False, str(path), message=failed, warnings=[str(exc)])
    ocr = page.ocr or {}
    speech = to_speech_text(page)[0].text if page.blocks else ""
    text = "\n".join(b.text for b in page.blocks if b.source == "ocr")
    if ocr.get("status") == "handwritten_offline":            # say why, not the generic message
        return ReadResult(False, str(path), speech=speech, message=speech, ocr=ocr, warnings=warnings)
    if ocr.get("status") != "done" or not text.strip():
        return ReadResult(False, str(path), message=failed, ocr=ocr, warnings=warnings)
    return ReadResult(True, str(path), speech=speech, text=text, ocr=ocr, warnings=warnings)
