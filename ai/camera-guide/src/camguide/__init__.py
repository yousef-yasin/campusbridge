"""CampusBridge camera guide (STB-16 to STB-23): spoken guidance to photograph a page, local
(OpenCV, no AI, no internet), auto-capture, then perspective correction and OCR through
document-reader."""
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[3] / "shared" / "src"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from .analyze import FrameReport, analyze, order_corners      # noqa: E402
from .capture import ReadResult, read_capture, scale_quad, straighten   # noqa: E402
from .commands import COMMANDS, PRIORITY, REASONS, say        # noqa: E402
from .config import GuideConfig                               # noqa: E402
from .guide import Advice, CameraGuide, failed_checks         # noqa: E402

__all__ = ["GuideConfig", "CameraGuide", "Advice", "FrameReport", "analyze", "failed_checks", "order_corners",
           "straighten", "scale_quad", "read_capture", "ReadResult", "COMMANDS", "REASONS", "PRIORITY", "say"]
