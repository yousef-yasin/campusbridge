"""Moving through a narrated file: where am I, next, previous, repeat, go to a unit or topic.

The frontend keeps one Navigator per open file and calls these on the student's commands.
Each call returns the segments to say. Position 0 is the intro; the last position is the outro.
"""
from typing import List, Optional, Union

from .files import UNIT_AR, UNIT_EN, FileNarration
from .segments import Segment
from .words import count, ordinal


class Navigator:
    def __init__(self, narration: FileNarration):
        self.n = narration
        self.en = narration.lang == "en"
        self.cursor = 0                                 # 0 intro, 1..len(units) units, len+1 outro

    # --- helpers -----------------------------------------------------------------------
    @property
    def _end(self) -> int:
        return len(self.n.units) + 1

    def _say(self, text: str) -> List[Segment]:
        return [Segment(text, "navigation", {"cursor": self.cursor})]

    def _current(self) -> List[Segment]:
        if self.cursor == 0:
            return [self.n.intro]
        if self.cursor == self._end:
            return [self.n.outro]
        return self.n.units[self.cursor - 1]

    def _word(self) -> str:
        return UNIT_EN[self.n.unit_type] if self.en else UNIT_AR[self.n.unit_type][0]

    # --- commands ----------------------------------------------------------------------
    def start(self) -> List[Segment]:
        self.cursor = 0
        return self._current()

    def repeat(self) -> List[Segment]:
        return self._current()

    def next(self) -> List[Segment]:
        if self.cursor == self._end:
            return self._say("This is the end of the file." if self.en else "هذه نهاية الملف.")
        self.cursor += 1
        return self._current()

    def previous(self) -> List[Segment]:
        if self.cursor == 0:
            return self._say("This is the beginning of the file." if self.en else "هذه بداية الملف.")
        self.cursor -= 1
        return self._current()

    def go_to(self, unit: Union[int, str]) -> List[Segment]:
        """Go to a page/slide number, or a sheet name."""
        for i, (number, sheet) in enumerate(zip(self.n.unit_numbers, self.n.sheets), 1):
            if str(unit) == str(number) or (sheet is not None and str(unit) == sheet):
                self.cursor = i
                return self._current()
        total = count(len(self.n.units), self.n.unit_type, "en" if self.en else "ar")
        word = self._word()
        if self.en:
            return self._say(f"There is no {word} {unit}; the file has {total}.")
        return self._say(f"الرقم {unit} غير موجود، والملف فيه {total}.")

    def go_to_topic(self, number: int) -> List[Segment]:
        topic = next((t for t in self.n.topics if t["number"] == number), None)
        if topic is None:
            total = count(len(self.n.topics), "topic", "en" if self.en else "ar")
            if self.en:
                return self._say(f"There is no topic {number}; the file has {total}.")
            return self._say(f"الموضوع رقم {number} غير موجود، والملف فيه {total}.")
        return self.go_to(topic["unit"])

    def where_am_i(self) -> List[Segment]:
        if self.cursor == 0:
            return self._say("Current position: the introduction of the file." if self.en else
                             "الموضع الحالي: مقدمة الملف.")
        if self.cursor == self._end:
            return self._say("Current position: the end of the file." if self.en else
                             "الموضع الحالي: نهاية الملف.")
        number = self.n.unit_numbers[self.cursor - 1]
        sheet = self.n.sheets[self.cursor - 1]
        total = len(self.n.units)
        topic = self._topic_at(number)
        word = self._word()
        if self.en:
            text = f"Current position: {word} {sheet or number} of {total}"
            if topic:
                text += f", in topic {topic['number']} of {len(self.n.topics)}: {topic['title']}"
        else:
            text = f"الموضع الحالي: {word} {sheet or number} من {total}"
            if topic:
                text += f"، ضمن الموضوع {ordinal(topic['number'], 'ar') or topic['number']} من {len(self.n.topics)}: {topic['title']}"
        return self._say(text + ".")

    def _topic_at(self, unit: int) -> Optional[dict]:
        found = None
        for topic in self.n.topics:
            if topic["unit"] <= unit:
                found = topic
        return found
