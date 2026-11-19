"""The language used when AI explains lecture content to a student.

One setting shared by every CampusBridge AI feature that writes explanations (image
descriptions now; the assistant and the narrator later), so a student gets the same style
everywhere. Read from the CB_EXPLAIN_LANGUAGE environment variable.

  ar     Arabic only; technical terms are translated.
  en     English only.
  mixed  (default) Arabic explanation; each technical term appears the first time in English
         with its Arabic meaning, then in English, so the student recognises it in the exam.

Text that is part of the material itself (text written inside an image, quotations) is never
translated: these modes apply to explanations only.
"""
import os
from typing import Optional

from .errors import ConfigError

ENV_VAR = "CB_EXPLAIN_LANGUAGE"
LANGUAGES = ("ar", "en", "mixed")
DEFAULT = "mixed"

INSTRUCTIONS = {
    "ar": ("Write every explanation in clear Modern Standard Arabic. Translate technical terms "
           "into Arabic; do not use English words."),
    "en": "Write every explanation in clear, simple English.",
    "mixed": ("Write every explanation in clear Modern Standard Arabic. Technical terms: the "
              "first time a term appears, write the English term first and then its Arabic "
              "meaning in parentheses, like this: «يوضح الشكل Central Limit Theorem (نظرية "
              "النهاية المركزية)». Never put the Arabic term first with the English in "
              "parentheses. After its first appearance, write the English term alone, like "
              "this: «وتنص Central Limit Theorem على أن ...». Keep symbols, variable names and "
              "numbers as they are."),
}

# How text-to-speech introduces an automatic description, per mode
AUTO_LABEL = {"ar": "وصف تلقائي:", "mixed": "وصف تلقائي:", "en": "Automatic description:"}
MANUAL_LABEL = {"ar": "صورة:", "mixed": "صورة:", "en": "Image:"}
NO_DESCRIPTION = {"ar": "صورة بدون وصف.", "mixed": "صورة بدون وصف.", "en": "Image without a description."}
# A description whose numbers were not found in the image (status needs_review)
REVIEW_NUMBERS = {"ar": "الأرقام كما وردت في الصورة:", "mixed": "الأرقام كما وردت في الصورة:",
                  "en": "Numbers as written in the image:"}
REVIEW_NO_TEXT = {"ar": "أرقام هذا الوصف غير مؤكدة.", "mixed": "أرقام هذا الوصف غير مؤكدة.",
                  "en": "The numbers in this description are not confirmed."}


def explain_language(value: Optional[str] = None) -> str:
    """The mode to use: an explicit value, else CB_EXPLAIN_LANGUAGE, else 'mixed'."""
    mode = (value or os.environ.get(ENV_VAR) or DEFAULT).strip().lower()
    if mode not in LANGUAGES:
        raise ConfigError(f"Unknown explanation language '{mode}' (use: {', '.join(LANGUAGES)})")
    return mode
