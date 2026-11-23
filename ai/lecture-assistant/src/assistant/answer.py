"""Answers from the retrieved lecture chunks only, with a source for every statement.

ask(question, courses, conversation) -> Answer:
- STU-17 «اشرح سلايد 7»: that slide is fetched directly and explained.
- STU-18 «لخص المحاضرة»: lecture-summarization summarises the lecture.
- STU-19 «اشرح مصطلح ...»: the glossary meaning comes first, then how the lectures use the term.
- Otherwise: hybrid search; when no chunk really matches, «هذا غير موجود في محاضرات المساق»
  (STU-20) without calling the text model.
After the answer: numbers and English terms must be in the retrieved chunks, glossary meanings
must match, and every statement needs a source; otherwise the status is needs_review.
"""
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from cb_shared import (AIError, AILimitError, AIQuotaError, AIUnavailableError, GeminiText, missing_english,
                       unverified_numbers)

from .arabic import normalize
from .chunks import Chunk
from .config import AssistantConfig, language_rules
from .history import QALog, new_conversation
from .search import Hit, HybridSearch
from .speech import NOT_FOUND, answer_speech, source_label, unavailable_message

PROMPT_VERSION = 2                       # 2: comparing excerpts allowed; text before figure labels
_STR = {"type": "string"}
SCHEMA = {"type": "object",
          "properties": {"found": {"type": "boolean"}, "answer": _STR,
                         "sources": {"type": "array", "items": _STR}},
          "required": ["found", "answer", "sources"]}

PROMPT = """You are the lecture assistant of CampusBridge. You answer questions of blind and \
visually impaired university students about their course lectures. The answer is read aloud.

Strict rules:
- Use ONLY the lecture excerpts below. Add no outside knowledge, no examples and no definitions \
that the excerpts do not give. Do not guess.
- Read every excerpt first. You may combine and compare facts that the excerpts state (for example, the difference between two terms that each excerpt defines). Set "found" to false and "answer" to "" only when the excerpts do not contain the facts the question needs.
- An image description lists what a figure shows, often labels without their meaning. Do not work out what a label covers from its position. When an excerpt's text states the fact, use the text.
- After every sentence that states something from the lectures, write the tag of the excerpt \
it comes from in square brackets, for example: "... normal distribution [S2]." List the tags \
you used in "sources".
- Copy every number exactly as written in the excerpts. Never calculate, round or convert.
- Short and clear for listening: 2 to 6 sentences, no tables, no lists, no markdown.
- The conversation so far only helps you understand what the question refers to. It is not a \
source: state nothing from it that the excerpts do not say.
{task}
Language: {language}
{glossary}
{history}
Lecture excerpts:
{excerpts}

Question: {question}"""

TASK_SLIDE = ("- The student asked you to explain {unit} {number} of {file}. Explain what it says, in its "
              "order, simply, using only its text. Set found to true unless it has no content.")
TASK_TERM = ("- The student asked about the term «{term}». Its meaning in the course glossary is «{meaning}». "
             "Explain how the lectures use the term, from the excerpts only. If the excerpts do not "
             "mention it, set found to false.")

UNIT_WORDS = r"(?:سلايد|سلايدات|الشريحه|شريحه|الشريحة|شريحة|السلايد|الصفحه|صفحه|الصفحة|صفحة|slide|page)"
SLIDE = re.compile(r"(?:اشرح|شرح|وضح|وضّح|فسر|فسّر|explain|describe)\b.*?" + UNIT_WORDS +
                   r"\s*(?:رقم|number|no\.?|#)?\s*(\d+)", re.IGNORECASE)
SUMMARY = re.compile(r"(?:لخص|لخّص|تلخيص|ملخص|summari[sz]e|summary)", re.IGNORECASE)
SUMMARY_WHAT = re.compile(r"(?:محاضر|الملف|ملف|lecture|file|chapter|الفصل|الوحده|الوحدة)", re.IGNORECASE)
TERM = re.compile(r"(?:مصطلح|term\b|معنى|معني|ماذا يعني|شو يعني|ايش يعني|define|definition|meaning of|what does .+ mean)",
                  re.IGNORECASE)


@dataclass
class Answer:
    question: str
    answer: str
    status: str                        # answered, not_found, needs_review, unavailable, clarify
    intent: str = "question"           # question, slide, summary, term
    sources: List[Dict[str, Any]] = field(default_factory=list)
    chunks: List[Dict[str, Any]] = field(default_factory=list)   # retrieved chunks (search details)
    problems: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    speech: str = ""
    conversation: str = ""
    language: str = "mixed"
    model: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _digits(text: str) -> str:
    return text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))


class Assistant:
    def __init__(self, store, embedder=None, engine=None, config: Optional[AssistantConfig] = None,
                 language: Optional[str] = None, log: Optional[QALog] = None, summarize=None):
        self.config = config or AssistantConfig.from_env()
        self.language, self.instruction = language_rules(language or self.config.language or None)
        self.store = store
        self.engine = engine or GeminiText(self.config.ai)
        self.glossary = self._glossary()
        self.search = HybridSearch(store, embedder, self.glossary, self.config)
        self.log = log or QALog(self.config.log_path)
        self._summarize = summarize                    # injected in tests; default: lecture-summarization

    @staticmethod
    def _glossary():
        from cb_shared import GlossaryError, load_glossary
        try:
            return load_glossary()
        except GlossaryError:
            return None

    # --- entry point -------------------------------------------------------------------
    def ask(self, question: str, courses: Sequence[str], conversation: Optional[str] = None,
            file: Optional[str] = None) -> Answer:
        conversation = conversation or new_conversation()
        history = self.log.recent(conversation, self.config.history_turns)
        q = _digits(question.strip())
        try:
            slide = SLIDE.search(q)
            if slide:
                result = self._slide(question, courses, int(slide.group(1)), file, history)
            elif SUMMARY.search(q) and (SUMMARY_WHAT.search(q) or len(q.split()) <= 3):
                result = self._summary(question, courses, file)
            else:
                entry = self._term(q) if TERM.search(q) or self._is_bare_term(q) else None
                result = self._term_answer(question, courses, entry, history) if entry else \
                    self._question(question, courses, history)
        except (AIUnavailableError, AILimitError) as exc:
            result = Answer(question, unavailable_message(exc, self.language), "unavailable", notes=[str(exc)])
        except AIError as exc:
            result = Answer(question, unavailable_message(exc, self.language), "unavailable", notes=[str(exc)])
        result.conversation, result.language = conversation, self.language
        result.speech = answer_speech(result, self.language)
        self.log.append(dict(result.to_dict(), courses=list(courses)))
        return result

    # --- kinds of questions ------------------------------------------------------------
    def _question(self, question, courses, history) -> Answer:
        context = history[-1]["question"] if history else ""
        found = self.search.search(question, courses, context)
        chunks = [h.to_dict() for h in found.hits]
        if not found.confident:
            return Answer(question, NOT_FOUND[self.lang_key], "not_found", chunks=chunks,
                          notes=found.notes + ["no lecture chunk matches well enough: the text model was not called"])
        return self._generate(question, [h.chunk for h in found.hits], history, "", "question",
                              chunks, found.notes)

    def _slide(self, question, courses, number, file, history) -> Answer:
        chunks = self.search.unit(courses, number, file)
        files = sorted({c.file for c in chunks})
        if len(files) > 1:
            return Answer(question, self._which_file(files), "clarify", "slide")
        if not chunks:
            return Answer(question, NOT_FOUND[self.lang_key], "not_found", "slide",
                          notes=[f"no unit {number} in the indexed lectures of these courses"])
        c = chunks[0]
        task = TASK_SLIDE.format(unit=c.unit_type, number=number, file=c.file)
        hits = [Hit(x, methods=["direct"]).to_dict() for x in chunks]
        return self._generate(question, chunks, history, task, "slide", hits, [])

    def _term(self, question: str):
        if not self.glossary:
            return None
        english = self.glossary.find(question)
        if english:
            return english[0]
        matched = [e for e in self.glossary.entries.values() if e.matches(question)]
        return max(matched, key=lambda e: len(e.meaning)) if matched else None

    def _is_bare_term(self, q: str) -> bool:
        """A question that is only a glossary term ("sampling distribution؟")."""
        e = self._term(q)
        return bool(e) and len(normalize(q).split()) <= len(e.term.split()) + 2

    def _term_answer(self, question, courses, entry, history) -> Answer:
        glossary_line = (f"{entry.term}: {entry.meaning}." if self.language != "en" else f"{entry.term}: see the course glossary.")
        found = self.search.search(f"{entry.term} ({entry.meaning})", courses)
        chunks = [h.to_dict() for h in found.hits]
        source = {"type": "glossary", "term": entry.term, "meaning": entry.meaning,
                  "glossary": self.glossary.info if self.glossary else None}
        if not found.confident:
            text = glossary_line + " " + {"en": "The lectures of this course do not explain it further.",
                                          "ar": "ولم يُشرح أكثر من ذلك في محاضرات المساق."}[self.lang_key]
            return Answer(question, text, "answered", "term", [source], chunks,
                          notes=found.notes + ["glossary only: no lecture chunk matches well enough"])
        task = TASK_TERM.format(term=entry.term, meaning=entry.meaning)
        result = self._generate(question, [h.chunk for h in found.hits], history, task, "term", chunks, found.notes)
        if result.status == "not_found":
            result.status, result.answer = "answered", glossary_line
        else:
            result.answer = f"{glossary_line} {result.answer}"
        result.sources.insert(0, source)
        return result

    def _summary(self, question, courses, file) -> Answer:
        from .indexer import units_from_chunks
        chunks = self.store.chunks(list(courses))
        files = sorted({c.file for c in chunks})
        if file:
            files = [f for f in files if f == file]
        elif len(files) > 1:
            named = [f for f in files if any(w in normalize(question) for w in self._file_words(f, chunks))]
            files = named or files
        if not files:
            return Answer(question, NOT_FOUND[self.lang_key], "not_found", "summary")
        if len(files) > 1:
            return Answer(question, self._which_file(files), "clarify", "summary")
        mine = [c for c in chunks if c.file == files[0]]
        units = units_from_chunks(mine)
        title = mine[0].file_title or files[0]
        summarize = self._summarize or self._default_summarize
        pages, whole, warnings = summarize(units, title)
        sources = [self._source(c) for c in mine if c.part == 1]
        if whole and whole.get("status") in ("ok", "needs_review", "manual") and whole.get("summary"):
            status = "needs_review" if whole["status"] == "needs_review" else "answered"
            return Answer(question, whole["summary"], status, "summary", sources,
                          problems=whole.get("problems") or [], notes=warnings, model=whole.get("model"))
        texts = [p["summary"] for p in pages if p.get("summary")]
        if not texts:
            reason = (whole or {}).get("reason") or "no page summaries"
            return Answer(question, unavailable_message(AIError(reason), self.language), "unavailable", "summary",
                          notes=warnings + [reason])
        problems = [x for p in pages for x in p.get("problems") or []]
        return Answer(question, " ".join(texts), "needs_review" if problems else "answered", "summary", sources,
                      problems=problems, notes=warnings)

    def _default_summarize(self, units, title):
        from cb_shared import use_module
        use_module("lecture-summarization")
        from summarizer import summarize_units
        return summarize_units(units, engine=self.engine, language=self.language, title=title)

    # --- the text model ----------------------------------------------------------------
    @property
    def lang_key(self) -> str:
        return "en" if self.language == "en" else "ar"

    def _generate(self, question, chunks: List[Chunk], history, task, intent, hit_dicts, notes) -> Answer:
        tags = {f"S{i}": c for i, c in enumerate(chunks, 1)}
        excerpts = "\n\n".join(c.render(tag) for tag, c in tags.items())
        source_text = [c.text for c in chunks] + [c.title for c in chunks] + [question]
        glossary = self.glossary.prompt_rules("\n".join(source_text), self.language) if self.glossary else ""
        past = ""
        if history:
            past = "Conversation so far (oldest first):\n" + "\n".join(
                f"Student: {h['question']}\nAssistant: {h['answer']}" for h in history) + "\n"
        prompt = PROMPT.format(task=task, language=self.instruction, glossary=glossary, history=past,
                               excerpts=excerpts, question=question)
        data = self.engine.generate_json(prompt, SCHEMA)
        model = getattr(self.engine, "last_model", None)
        notes = list(notes) + list(getattr(self.engine, "notes", []) or [])
        raw = (data.get("answer") or "").strip()
        if not data.get("found") or not raw:
            return Answer(question, NOT_FOUND[self.lang_key], "not_found", intent, chunks=hit_dicts,
                          notes=notes + ["the model found no answer in the retrieved chunks"], model=model)
        used = list(dict.fromkeys(re.findall(r"\[(S\d+)\]", raw) + [s for s in data.get("sources") or []
                                                                    if isinstance(s, str)]))
        problems = self._check(raw, chunks, question, tags)
        sources = [dict(self._source(tags[t]), tag=t) for t in used if t in tags]
        if not sources:
            problems.append("the answer names no source")
        text = self._cite(raw, tags)
        return Answer(question, text, "needs_review" if problems else "answered", intent, sources, hit_dicts,
                      problems, notes, model=model)

    def _check(self, raw: str, chunks: List[Chunk], question: str, tags: Dict[str, Chunk]) -> List[str]:
        problems = []
        bad = sorted({t for t in re.findall(r"\[(S\d+)\]", raw) if t not in tags})
        if bad:
            problems.append(f"sources that were not retrieved: {', '.join(bad)}")
        plain = re.sub(r"\s*\[S\d+\]", "", raw)
        source = [c.text for c in chunks] + [c.title for c in chunks] + [question]
        numbers = unverified_numbers([plain], source)
        if numbers:
            problems.append(f"numbers not in the retrieved lectures: {', '.join(numbers)}")
        if self.language != "en":
            english = missing_english([plain], "\n".join(source))
            if english:
                problems.append(f"English words not in the retrieved lectures: {', '.join(english)}")
        if self.glossary and self.language != "en":
            problems += [f"term meaning differs from the glossary: {p}" for p in self.glossary.wrong_meanings([plain])]
        unsourced = [s for s in re.split(r"(?<=[.!?؟])\s+(?!\[S)", raw.strip())
                     if len(s.split()) > 3 and not re.search(r"\[S\d+\]", s)]
        if unsourced:
            problems.append(f"{len(unsourced)} sentence(s) without a source")
        return problems

    def _cite(self, raw: str, tags: Dict[str, Chunk]) -> str:
        """[S2] -> [CLT.pptx، سلايد 7] (one bracket for neighbouring tags)."""
        def repl(match):
            names = list(dict.fromkeys(source_label(self._source(tags[t]), self.language)
                                       for t in re.findall(r"S\d+", match.group(0)) if t in tags))
            return f" [{'؛ '.join(names) if self.lang_key == 'ar' else '; '.join(names)}]" if names else ""
        return re.sub(r"\s*(?:\[S\d+\]\s*)+", repl, raw).strip()

    @staticmethod
    def _source(c: Chunk) -> Dict[str, Any]:
        return {"type": "lecture", "course": c.course, "file": c.file, "file_title": c.file_title,
                "unit": c.unit, "unit_type": c.unit_type, "title": c.title, "blocks": c.block_ids,
                "from": c.sources}

    @staticmethod
    def _file_words(file: str, chunks: List[Chunk]) -> List[str]:
        title = next((c.file_title for c in chunks if c.file == file and c.file_title), "")
        return [w for w in normalize(f"{file} {title}").replace("_", " ").replace(".", " ").split() if len(w) > 3]

    def _which_file(self, files: List[str]) -> str:
        if self.lang_key == "en":
            return "Which lecture? " + ", ".join(files) + "."
        return "أي محاضرة؟ " + "، ".join(files) + "."
