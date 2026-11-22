"""CampusBridge lecture summarization: page summaries, key points and terms, and a file summary.

Input: numbered text units (cb_shared.units) - pages of a document from document-reader, or
later parts of a lecture transcript. Text is sent to Google's Gemini servers.
"""
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[3] / "shared" / "src"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from .config import SummaryConfig                                   # noqa: E402
from .summarize import FileSummarizer, PageSummarizer, summarize_units   # noqa: E402
from .speech import file_summary_speech, summary_speech             # noqa: E402

__all__ = ["SummaryConfig", "PageSummarizer", "FileSummarizer", "summarize_units",
           "summary_speech", "file_summary_speech"]
