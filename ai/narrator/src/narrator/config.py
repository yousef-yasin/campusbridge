"""Narrator settings. Every value can be overridden with a NARRATOR_* environment variable."""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

from .errors import ConfigError

_ROOT = Path(__file__).resolve().parents[2]                 # ai/narrator
LANGUAGES = ("ar", "en", "mixed")                           # same values as CB_EXPLAIN_LANGUAGE


@dataclass
class NarratorConfig:
    # Explanation language shared by CampusBridge AI features (CB_EXPLAIN_LANGUAGE):
    # "ar" and "mixed" give Arabic guidance phrases, "en" English ones. Content is never translated.
    language: str = ""                     # "" = CB_EXPLAIN_LANGUAGE, else "mixed"
    timezone: str = "Asia/Amman"           # dates and times are said in this zone
    max_topics_listed: int = 5             # the intro names this many topics, then "and N more"
    max_table_rows: int = 10               # rows read per table; a sentence tells how many remain
    number_rows_from: int = 4              # tables with at least this many rows say "row 2 of 8"
    words_per_minute: int = 130            # for the listening-time estimate
    quiz_warnings: tuple = (5, 1)          # minutes left at which a quiz warns
    reader_path: str = str(_ROOT.parent / "document-reader" / "src")

    @classmethod
    def from_env(cls) -> "NarratorConfig":
        e = os.environ.get
        warnings = e("NARRATOR_QUIZ_WARNINGS")
        return cls(language=e("NARRATOR_LANGUAGE", e("CB_EXPLAIN_LANGUAGE", cls.language)),
                   timezone=e("NARRATOR_TIMEZONE", cls.timezone),
                   max_topics_listed=int(e("NARRATOR_MAX_TOPICS", cls.max_topics_listed)),
                   max_table_rows=int(e("NARRATOR_MAX_TABLE_ROWS", cls.max_table_rows)),
                   number_rows_from=int(e("NARRATOR_NUMBER_ROWS_FROM", cls.number_rows_from)),
                   words_per_minute=int(e("NARRATOR_WORDS_PER_MINUTE", cls.words_per_minute)),
                   quiz_warnings=tuple(int(x) for x in warnings.split(",")) if warnings else cls.quiz_warnings,
                   reader_path=e("NARRATOR_READER_PATH", cls.reader_path)).validate()

    def validate(self) -> "NarratorConfig":
        self.language = (self.language or "mixed").strip().lower()
        if self.language not in LANGUAGES:
            raise ConfigError(f"Unknown language '{self.language}' (use: {', '.join(LANGUAGES)})")
        if min(self.max_topics_listed, self.max_table_rows, self.number_rows_from, self.words_per_minute) < 1:
            raise ConfigError("max_topics_listed, max_table_rows, number_rows_from and words_per_minute must be >= 1")
        self.tz()
        return self

    @property
    def phrase_language(self) -> str:
        """Language of the guidance phrases: English only in "en" mode."""
        return "en" if self.language == "en" else "ar"

    def tz(self) -> tzinfo:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(self.timezone)
        except Exception:
            if self.timezone == "Asia/Amman":              # UTC+3 all year since 2022
                return timezone(timedelta(hours=3), "Asia/Amman")
            raise ConfigError(f"Unknown time zone '{self.timezone}' (pip install tzdata)") from None

    def now(self) -> datetime:
        return datetime.now(self.tz())
