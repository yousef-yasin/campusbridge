"""Questions as text for text-to-speech: «سؤال: ... الجواب: ...»."""
from typing import Any, Dict, List, Tuple

LABELS = {"ar": ("سؤال:", "الجواب:"), "en": ("Question:", "Answer:")}


def _sentence(text: str) -> str:
    text = " ".join(str(text).split())
    return text if not text or text.endswith(tuple(".!?؟…:")) else f"{text}."


def question_parts(result: Dict[str, Any]) -> List[Tuple[str, str]]:
    """[(«سؤال: ...», «الجواب: ...»)] for a unit result; [] when it has no questions."""
    if result.get("status") not in ("ok", "needs_review", "manual"):
        return []
    q_label, a_label = LABELS["en" if result.get("language") == "en" else "ar"]
    return [(_sentence(f"{q_label} {q['question']}"), _sentence(f"{a_label} {q['answer']}"))
            for q in result.get("questions") or [] if q.get("question") and q.get("answer")]


def questions_speech(result: Dict[str, Any]) -> str:
    return "\n\n".join(f"{q}\n{a}" for q, a in question_parts(result))
