"""Narrating a quiz: intro, questions with their options, answer confirmation, time warnings.

The correct answer is NEVER read. Only a whitelist of fields is copied from the platform data
(see public_quiz); answer keys, feedback, explanations and "correct" flags are dropped on input,
so no later code can read them by mistake.
"""
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Union

from .common import Narrator, require_dict, text_field
from .dates import parse
from .errors import InputError
from .segments import Segment
from .words import letters, number, sentence, sentences

TYPES = {"multiple_choice": ("اختيار من متعدد", "Multiple choice"),
         "true_false": ("صح أو خطأ", "True or false"),
         "short_answer": ("إجابة قصيرة", "Short answer")}
_QUIZ_FIELDS = ("title", "course", "duration_minutes", "attempts_allowed", "attempts_used", "opens_at", "closes_at")


def public_quiz(data: Dict[str, Any]) -> Dict[str, Any]:
    """Only what may be read aloud. Everything else (correct answers included) is dropped."""
    data = require_dict(data, "quiz")
    quiz = {k: data[k] for k in _QUIZ_FIELDS if data.get(k) not in (None, "")}
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise InputError("quiz.questions must be a non-empty list")
    quiz["questions"] = []
    for n, q in enumerate(questions, 1):
        q = require_dict(q, f"question {n}")
        kind = q.get("type")
        if kind is not None and kind not in TYPES:
            raise InputError(f"question {n}: unknown type {kind!r} (use: {', '.join(TYPES)})")
        text = text_field(q, "text")
        if not text:
            raise InputError(f"question {n}: text is missing")
        options = []
        for o in q.get("options") or []:
            label = o.get("text") if isinstance(o, dict) else o      # dict options: only their text
            if label is None or not str(label).strip():
                raise InputError(f"question {n}: an option has no text")
            options.append(" ".join(str(label).split()))
        quiz["questions"].append({"type": kind, "points": q.get("points"), "text": text, "options": options})
    return quiz


class QuizNarrator(Narrator):
    def __init__(self, quiz: Dict[str, Any], config=None, now=None):
        super().__init__(config, now)
        self.quiz = public_quiz(quiz)
        self.questions = self.quiz["questions"]
        self.warned: Set[int] = set()

    # --- intro -------------------------------------------------------------------------
    def intro(self) -> List[Segment]:
        q, en = self.quiz, self.en
        n = len(self.questions)
        if q.get("title"):
            parts = [f"Quiz: {q['title']}" if en else f"كويز: {q['title']}"]
        else:
            parts = ["Quiz" if en else "كويز"]
        if q.get("course"):
            parts.append(f"Course: {q['course']}" if en else f"مساق {q['course']}")
        parts.append(f"It has {self.count(n, 'question')}" if en else f"يحتوي على {self.count(n, 'question')}")
        if q.get("duration_minutes"):
            span = self.count(q["duration_minutes"], "minute", one=False)
            parts.append(f"Time limit: {span}" if en else f"المدة: {span}")
        if q.get("attempts_allowed"):
            allowed = int(q["attempts_allowed"])
            parts.append(f"Attempts allowed: {allowed}" if en else f"المحاولات المسموحة: {self.count(allowed, 'attempt')}")
            if q.get("attempts_used") is not None:
                left = max(allowed - int(q["attempts_used"]), 0)
                parts.append(f"Attempts left: {left}" if en else
                             f"المحاولات المتبقية: {self.count(left, 'attempt') if left else 'لا يوجد'}")
        if q.get("opens_at") and parse(q["opens_at"], self.tz, "opens_at")[0] > self.now:
            when = self.when(q["opens_at"], "opens_at")
            parts.append(f"Opens {when}, {self.until(q['opens_at'], 'opens_at')}" if en else
                         f"يُفتح {when}، {self.until(q['opens_at'], 'opens_at')}")
        if q.get("closes_at"):
            when, left = self.when(q["closes_at"], "closes_at"), self.remaining(q["closes_at"], "closes_at")
            parts.append(f"Deadline: closes {when}, {left}" if en else f"الموعد: يُغلق {when}، {left}")
        return [Segment(sentences(parts), "intro", {"questions": n})]

    # --- questions ---------------------------------------------------------------------
    def _q(self, number_: int) -> Dict[str, Any]:
        if not 1 <= number_ <= len(self.questions):
            raise InputError(f"question {number_} does not exist (1-{len(self.questions)})")
        return self.questions[number_ - 1]

    def _options(self, q: Dict[str, Any]) -> List[str]:
        if q["options"]:
            return q["options"]
        if q["type"] == "true_false":
            return ["True", "False"] if self.en else ["صح", "خطأ"]
        return []

    def question(self, number_: int) -> List[Segment]:
        q, en = self._q(number_), self.en
        total = len(self.questions)
        pos = {"question": number_, "questions": total}
        out = [Segment(f"Question {number_} of {total}." if en else f"سؤال {number_} من {total}.", "position", pos)]
        about = []
        if q["type"]:
            about.append(TYPES[q["type"]][1 if en else 0])
        if q["points"] is not None:
            points = number(q["points"])
            about.append(f"{points} point{'' if q['points'] == 1 else 's'}" if en else f"العلامة: {points}")
        if about:
            out.append(Segment(sentence(", ".join(about) if en else "، ".join(about)), "question", pos))
        out.append(Segment(sentence(q["text"]), "question", dict(pos, part="text")))
        for letter, option in zip(letters(self.lang), self._options(q)):
            text = f"Option {letter}: {option}" if en else f"الخيار {letter}: {option}"
            out.append(Segment(sentence(text), "options", dict(pos, option=letter)))
        if q["type"] == "short_answer" and not q["options"]:
            out.append(Segment("The answer is written." if en else "الإجابة كتابةً.", "options", pos))
        return out

    # --- answering ---------------------------------------------------------------------
    def _chosen(self, q: Dict[str, Any], answer: Union[int, str, bool, None]):
        """(letter, option text) for a chosen option, or (None, text) for a written answer."""
        options = self._options(q)
        marks = letters(self.lang)
        if isinstance(answer, bool) and q["type"] == "true_false":
            answer = 0 if answer else 1
        if isinstance(answer, int) and not isinstance(answer, bool) and options:
            if not 0 <= answer < len(options):
                raise InputError(f"answer {answer} is not an option (0-{len(options) - 1})")
            return marks[answer], options[answer]
        if isinstance(answer, str) and options:
            for i, (mark, option) in enumerate(zip(marks, options)):
                if answer.strip() in (mark, letters("en")[i], option):
                    return mark, option
            raise InputError(f"answer {answer!r} is not one of the options")
        return None, (" ".join(str(answer).split()) if answer is not None else "")

    def confirm(self, number_: int, answer) -> List[Segment]:
        """Said before an answer is sent: the chosen option, then a question."""
        q, en = self._q(number_), self.en
        mark, text = self._chosen(q, answer)
        pos = {"question": number_, "questions": len(self.questions)}
        if not text:
            return [Segment(f"No answer for question {number_} yet." if en else
                            f"لا توجد إجابة للسؤال {number_} بعد.", "confirm", pos)]
        if mark:
            chosen = (f"Selected answer for question {number_}: option {mark}: {text}" if en else
                      f"الإجابة المختارة للسؤال {number_}: الخيار {mark}: {text}")
        else:
            chosen = (f"Written answer for question {number_}: {text}" if en else
                      f"الإجابة المكتوبة للسؤال {number_}: {text}")
        ask = "Submit this answer?" if en else "هل يتم إرسال هذه الإجابة؟"
        return [Segment(f"{sentence(chosen)} {ask}", "confirm", dict(pos, option=mark))]

    def confirm_submit(self, answers: Dict[int, Any]) -> List[Segment]:
        """Before the whole quiz is sent: how many questions have an answer, and which do not."""
        total = len(self.questions)
        empty = [n for n in range(1, total + 1) if answers.get(n) in (None, "")]
        done = total - len(empty)
        if self.en:
            parts = [f"Answered questions: {done} of {total}"]
            if empty:
                parts.append(f"Without an answer: question{'s' if len(empty) > 1 else ''} {', '.join(map(str, empty))}")
            text = sentences(parts) + " Submit the quiz?"
        else:
            parts = [f"عدد الأسئلة المجاب عنها: {done} من {total}"]
            if empty:
                parts.append(f"بدون إجابة: {'الأسئلة' if len(empty) > 1 else 'السؤال'} {'، '.join(map(str, empty))}")
            text = sentences(parts) + " هل يتم إرسال الكويز؟"
        return [Segment(text, "confirm", {"answered": done, "questions": total})]

    # --- time --------------------------------------------------------------------------
    def time_warning(self, minutes: int) -> Segment:
        if self.en:
            text = f"Warning: {self.count(minutes, 'minute')} left in the quiz."
        else:
            text = f"تنبيه: باقي {self.count(minutes, 'minute')} على انتهاء الكويز."
        return Segment(text, "time_warning", {"minutes_left": minutes})

    def warnings_due(self, ends_at, now=None) -> List[Segment]:
        """Warnings to say now (5 and 1 minutes by default), each once. Call it periodically."""
        end, _ = parse(ends_at, self.tz, "ends_at")
        left = end - (now.astimezone(self.tz) if now else self.config.now())
        if left <= timedelta(0):
            return []
        crossed = [m for m in self.config.quiz_warnings if left <= timedelta(minutes=m) and m not in self.warned]
        if not crossed:
            return []
        self.warned.update(m for m in self.config.quiz_warnings if left <= timedelta(minutes=m))
        return [self.time_warning(min(crossed))]

    def all_segments(self) -> List[Segment]:
        out = self.intro()
        for n in range(1, len(self.questions) + 1):
            out += self.question(n)
        return out
