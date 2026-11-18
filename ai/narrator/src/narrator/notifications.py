"""Narrating notifications. Emergencies have priority: they are always read first."""
from typing import Any, Dict, List

from .common import Narrator, require_dict, text_field
from .errors import InputError
from .segments import Segment
from .words import sentences

TYPES = ("lecture_reminder", "room_change", "quiz_reminder", "assignment_due", "emergency", "technical_issue")


class NotificationNarrator(Narrator):
    def text(self, data: Dict[str, Any]) -> str:
        n = require_dict(data, "notification")
        kind = n.get("type")
        if kind not in TYPES:
            raise InputError(f"notification type must be one of {', '.join(TYPES)}")
        en, f = self.en, lambda key: text_field(n, key)
        sep = ", " if en else "، "
        if kind in ("lecture_reminder", "room_change"):
            course = f("course")
            what = (f"{course} lecture" if course else "Lecture") if en else (f"محاضرة مساق {course}" if course else "محاضرة")
            items = [what]
            if n.get("starts_at"):
                items += [self.when(n["starts_at"], "starts_at"), self.until(n["starts_at"], "starts_at")]
            if kind == "lecture_reminder":
                if f("room"):
                    items.append(f"in room {f('room')}" if en else f"في القاعة {f('room')}")
                head = "Lecture reminder" if en else "تذكير بمحاضرة"
                if not en and items[0].startswith("محاضرة"):
                    items[0] = items[0].replace("محاضرة ", "", 1) if course else None
            else:
                if not f("new_room"):
                    raise InputError("room_change needs new_room")
                if f("old_room"):
                    items.append(f"moved from room {f('old_room')} to room {f('new_room')}" if en else
                                 f"انتقلت من القاعة {f('old_room')} إلى القاعة {f('new_room')}")
                else:
                    items.append(f"now in room {f('new_room')}" if en else f"أصبحت في القاعة {f('new_room')}")
                head = "Room change" if en else "تغيير قاعة"
            body = sep.join(i for i in items if i)
            parts = [f"{head}: {body}" if body else head]
        elif kind in ("quiz_reminder", "assignment_due"):
            quiz = kind == "quiz_reminder"
            head = ("Quiz reminder" if quiz else "Assignment due") if en else ("تذكير بكويز" if quiz else "موعد تسليم واجب")
            items = [f("title"), (f"course {f('course')}" if en else f"مساق {f('course')}") if f("course") else None]
            deadline = n.get("closes_at" if quiz else "due_at")
            if deadline:
                when = self.when(deadline)
                items.append((f"closes {when}" if quiz else f"due {when}") if en else
                             (f"يُغلق {when}" if quiz else f"الموعد {when}"))
                items.append(self.remaining(deadline))
            body = sep.join(i for i in items if i)
            parts = [f"{head}: {body}" if body else head]
        else:
            emergency = kind == "emergency"
            head = ("Emergency alert" if emergency else "Technical issue") if en else \
                   ("تنبيه طوارئ" if emergency else "مشكلة تقنية")
            message = f("message")
            if not message:
                raise InputError(f"{kind} needs message")
            parts = [f"{head}: {message}"]
            if emergency:
                if f("location"):
                    parts.append(f"Location: {f('location')}" if en else f"المكان: {f('location')}")
                if f("instructions"):
                    parts.append(f"Instructions: {f('instructions')}" if en else f"التعليمات: {f('instructions')}")
            else:
                if f("service"):
                    parts.append(f"Affected service: {f('service')}" if en else f"الخدمة المتأثرة: {f('service')}")
                if n.get("expected_fix_at"):
                    when = self.when(n["expected_fix_at"], "expected_fix_at")
                    parts.append(f"Expected fix: {when}" if en else f"الحل المتوقع: {when}")
        if n.get("sent_at"):
            when = self.when(n["sent_at"], "sent_at")
            parts.append(f"Sent {when}" if en else f"وقت الإشعار: {when}")
        return sentences(parts)

    def notifications(self, items: List[Dict[str, Any]]) -> List[Segment]:
        """Emergencies first (in their order), then the rest in the order given."""
        if not isinstance(items, list) or not items:
            raise InputError("notifications must be a non-empty list")
        for item in items:
            require_dict(item, "notification")
        ordered = [i for i in items if i.get("type") == "emergency"] + [i for i in items if i.get("type") != "emergency"]
        total = len(ordered)
        out: List[Segment] = []
        if total > 1:
            summary = self.you_have(total, "notification")
            if any(i.get("type") == "emergency" for i in ordered):
                summary += " Emergency alerts first." if self.en else " تنبيهات الطوارئ أولاً."
            out.append(Segment(summary, "summary", {"count": total}))
        for index, item in enumerate(ordered, 1):
            text = self.text(item)
            if total > 1:
                text = (f"Notification {index} of {total}. " if self.en else f"الإشعار {index} من {total}. ") + text
            emergency = item.get("type") == "emergency"
            out.append(Segment(text, "emergency" if emergency else "notification",
                               {"index": index, "count": total, "type": item["type"],
                                "priority": "high" if emergency else "normal"}))
        return out
