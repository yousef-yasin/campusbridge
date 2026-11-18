"""Narrating chat messages: sender and role, time, text, attachments."""
from typing import Any, Dict, List

from .common import Narrator, require_dict, text_field
from .errors import InputError
from .segments import Segment
from .words import sentence, sentences

# role -> (Arabic, English); gender-neutral group nouns ("من هيئة التدريس")
ROLES = {"instructor": ("هيئة التدريس", "instructor"),
         "teaching_assistant": ("فريق التدريس", "teaching assistant"),
         "student": ("الطلبة", "student"),
         "admin": ("إدارة المنصة", "platform administration"),
         "support": ("الدعم الفني", "technical support")}


class ChatNarrator(Narrator):
    def message(self, data: Dict[str, Any], index: int = 0, total: int = 1) -> Segment:
        m, en = require_dict(data, "message"), self.en
        sender, role = text_field(m, "sender"), text_field(m, "role")
        text = text_field(m, "text")
        files = self.attachments(m.get("attachments"), verb_ar="تحتوي")
        if not text and not files:
            raise InputError("a message needs text or attachments")
        role_name = ROLES[role][1 if en else 0] if role in ROLES else role
        if en:
            head = f"Message {index} of {total}: from" if total > 1 else "Message from"
            who = ", ".join(p for p in (sender, role_name) if p)
        else:
            head = f"الرسالة {index} من {total}: من" if total > 1 else "رسالة من"
            who = "، من ".join(p for p in (sender, role_name) if p)
        first = f"{head} {who}" if who else head.rsplit(" ", 1)[0]
        if m.get("sent_at"):
            first += f", {self.when(m['sent_at'], 'sent_at')}" if en else f"، {self.when(m['sent_at'], 'sent_at')}"
        parts = [first, (f"Message: {text}" if en else f"نص الرسالة: {text}") if text else None, files]
        return Segment(sentences(parts), "message", {"index": index or 1, "count": total})

    def messages(self, items: List[Dict[str, Any]]) -> List[Segment]:
        if not isinstance(items, list) or not items:
            raise InputError("messages must be a non-empty list")
        if len(items) == 1:
            return [self.message(items[0])]
        out = [Segment(self.you_have(len(items), "message"), "summary", {"count": len(items)})]
        return out + [self.message(m, i, len(items)) for i, m in enumerate(items, 1)]
