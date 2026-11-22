"""Narrating an assignment: title, course, deadline and time left, description, attachments, status."""
from typing import Any, Dict, List

from .common import Narrator, require_dict, text_field
from .errors import InputError
from .segments import Segment
from .words import number, sentence, sentences

STATUSES = ("not_submitted", "submitted", "late", "graded")


class AssignmentNarrator(Narrator):
    def narrate(self, data: Dict[str, Any]) -> List[Segment]:
        a, en = require_dict(data, "assignment"), self.en
        out: List[Segment] = []
        title, course = text_field(a, "title"), text_field(a, "course")
        head = [(f"Assignment: {title}" if en else f"واجب: {title}") if title else ("Assignment" if en else "واجب")]
        if course:
            head.append(f"Course: {course}" if en else f"مساق {course}")
        out.append(Segment(sentences(head), "assignment", {"part": "title"}))
        if a.get("due_at"):
            when, left = self.when(a["due_at"], "due_at"), self.remaining(a["due_at"], "due_at")
            out.append(Segment(sentence(f"Due {when}, {left}" if en else f"الموعد: {when}، {left}"),
                               "assignment", {"part": "due"}))
        description = text_field(a, "description")
        if description:
            out.append(Segment(sentence(f"Description: {description}" if en else f"الوصف: {description}"),
                               "assignment", {"part": "description"}))
        files = self.attachments(a.get("attachments"), verb_ar="يحتوي الواجب")
        if files:
            out.append(Segment(sentence(files), "assignment", {"part": "attachments"}))
        status = self._status(a.get("submission"))
        if status:
            out.append(Segment(sentence(status), "assignment", {"part": "submission"}))
        return out

    def _status(self, submission) -> str:
        if submission is None:
            return ""
        if isinstance(submission, str):
            submission = {"status": submission}
        submission = require_dict(submission, "submission")
        status = submission.get("status")
        if status not in STATUSES:
            raise InputError(f"submission.status must be one of {', '.join(STATUSES)}")
        en = self.en
        when = self.when(submission["submitted_at"], "submitted_at") if submission.get("submitted_at") else ""
        if status == "not_submitted":
            return "Submission: not submitted yet" if en else "حالة التسليم: لم يُسلَّم بعد"
        if status in ("submitted", "late"):
            late = status == "late"
            if en:
                return f"Submission: submitted{' late' if late else ''}{' ' + when if when else ''}"
            return f"حالة التسليم: تم التسليم{' متأخراً' if late else ''}{' ' + when if when else ''}"
        grade, best = submission.get("grade"), submission.get("max_grade")
        mark = ""
        if grade is not None:
            mark = (f", mark {number(grade)}" + (f" out of {number(best)}" if best is not None else "")) if en else \
                   (f"، العلامة {number(grade)}" + (f" من {number(best)}" if best is not None else ""))
        return (f"Submission: submitted and graded{mark}" if en else f"حالة التسليم: تم التسليم والتصحيح{mark}")
