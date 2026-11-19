"""Exam-style questions with short answers, from the text of one page or slide only."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from cb_shared import GeminiText, GeminiTextConfig, TextUnit, UnitJob, missing_english, unverified_numbers, use_module

_ROOT = Path(__file__).resolve().parents[2]          # ai/question-generation
PROMPT_VERSION = 2                       # 2: glossary meanings
_STR = {"type": "string"}

SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": {"type": "object", "properties": {
            "question": _STR, "answer": _STR, "block": _STR}, "required": ["question", "answer", "block"]}},
    },
    "required": ["questions"],
}

PROMPT = """You write practice questions for blind and visually impaired university students, \
who will hear each question, think, and then hear the answer.

Write 2 to 3 exam-style questions about ONE {unit} of lecture material, with short answers.

Strict rules:
- Every question must be answerable from the text of this {unit} alone, and every answer must
  be stated in it. Use no outside knowledge.
- If the text does not support a good question, write fewer questions, or none (an empty
  list). Never invent a question about something the text does not say.
- No question about the title alone, page numbers or the layout.
- Answers are short: a phrase or one or two sentences. Copy numbers exactly as written; never
  calculate a new number.
- block: the id of the block the answer comes from (for example "b2").
- Ask about understanding (what, why, how, compare), not only about remembering one word.

Language: {language}
This applies to questions and answers. Technical terms follow the same rule.
{glossary}
The {unit} ({label}), one line per block:
{content}"""


def language_rules(mode=None):
    from cb_shared.explain import INSTRUCTIONS, explain_language
    mode = explain_language(mode)
    return mode, INSTRUCTIONS[mode]


@dataclass
class QuestionConfig:
    language: str = ""
    cache_dir: str = str(_ROOT / "questions-cache")     # reviewable JSON, git-ignored
    min_words: int = 25
    max_questions: int = 3
    ai: GeminiTextConfig = field(default_factory=GeminiTextConfig)

    @classmethod
    def from_env(cls) -> "QuestionConfig":
        e = os.environ.get
        env_files = [str(_ROOT / ".env"), str(_ROOT.parent / "document-reader" / ".env")]
        return cls(language=e("CB_EXPLAIN_LANGUAGE", ""), cache_dir=e("QUESTIONS_CACHE_DIR", cls.cache_dir),
                   min_words=int(e("QUESTIONS_MIN_WORDS", cls.min_words)),
                   ai=GeminiTextConfig.from_env("QUESTIONS", env_files))


class QuestionGenerator(UnitJob):
    kind = "questions"
    version = PROMPT_VERSION
    schema = SCHEMA
    manual_template = {"questions": []}

    def __init__(self, config: Optional[QuestionConfig] = None, engine=None, language: Optional[str] = None):
        self.config = config or QuestionConfig.from_env()
        mode, self.instruction = language_rules(language or self.config.language or None)
        super().__init__(engine or GeminiText(self.config.ai), self.config.cache_dir, mode)
        self.min_words = self.config.min_words

    def prompt(self, unit: TextUnit) -> str:
        return PROMPT.format(unit=unit.unit_type, label=unit.label, language=self.instruction,
                             content=unit.render(), glossary=self.glossary_rules(unit))

    def one(self, unit: TextUnit) -> Dict[str, Any]:
        result = super().one(unit)
        items = [q for q in result.get("questions") or [] if isinstance(q, dict)][: self.config.max_questions]
        for q in items:                                         # every answer points to its page
            q.setdefault("page", unit.number)
            q.setdefault("unit_type", unit.unit_type)
        if "questions" in result:
            result["questions"] = items
        return result

    def check(self, data: Dict[str, Any], unit: TextUnit) -> List[str]:
        items = [q for q in data.get("questions") or [] if isinstance(q, dict)]
        texts = [t for q in items for t in (q.get("question") or "", q.get("answer") or "")]
        problems = []
        numbers = unverified_numbers(texts, [unit.text, unit.title])
        if numbers:
            problems.append(f"numbers not in the {unit.unit_type}: {', '.join(numbers)}")
        if self.language != "en":
            english = missing_english(texts, unit.text)
            if english:
                problems.append(f"English words not in the {unit.unit_type}: {', '.join(english)}")
        bad = [q.get("block") for q in items if not unit.block(str(q.get("block")))]
        if bad:
            problems.append(f"answers linked to blocks that do not exist: {', '.join(map(str, bad))}")
        problems += self.glossary_problems(texts)
        return problems


def generate_questions(units: Iterable[TextUnit], config: Optional[QuestionConfig] = None, engine=None,
                       language: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    gen = QuestionGenerator(config, engine, language)
    return gen.run(units), gen.warnings
