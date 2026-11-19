"""CampusBridge question generation: exam-style questions with short answers, per page or slide.

Input: numbered text units (cb_shared.units). Every answer is linked to its page and block.
Text is sent to Google's Gemini servers.
"""
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[3] / "shared" / "src"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from .generate import QuestionConfig, QuestionGenerator, generate_questions   # noqa: E402
from .speech import question_parts, questions_speech                          # noqa: E402

__all__ = ["QuestionConfig", "QuestionGenerator", "generate_questions", "questions_speech", "question_parts"]
