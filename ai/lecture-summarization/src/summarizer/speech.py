"""Summaries as text for text-to-speech."""
from typing import Any, Dict, Optional

LABELS = {
    "ar": {"auto": "ملخص تلقائي:", "manual": "ملخص:", "points": "النقاط المهمة:", "terms": "المصطلحات:",
           "file": "ملخص تلقائي للملف:", "file_manual": "ملخص الملف:"},
    "en": {"auto": "Automatic summary:", "manual": "Summary:", "points": "Key points:", "terms": "Terms:",
           "file": "Automatic summary of the file:", "file_manual": "Summary of the file:"},
}


def _labels(mode: Optional[str]) -> Dict[str, str]:
    return LABELS["en" if mode == "en" else "ar"]


def _sentence(text: str) -> str:
    text = " ".join(str(text).split())
    return text if not text or text.endswith(tuple(".!?؟…:")) else f"{text}."


def summary_speech(result: Dict[str, Any], points: bool = True, terms: bool = True) -> str:
    """«ملخص تلقائي: ...», then the key points and terms. '' when there is no summary."""
    if result.get("status") not in ("ok", "needs_review", "manual") or not result.get("summary"):
        return ""
    lab = _labels(result.get("language"))
    parts = [_sentence(f"{lab['manual' if result.get('status') == 'manual' else 'auto']} {result['summary']}")]
    if points and result.get("points"):
        parts.append(lab["points"])
        parts += [_sentence(p["text"] if isinstance(p, dict) else p) for p in result["points"]]
    if terms and result.get("terms"):
        parts.append(lab["terms"])
        parts += [_sentence(f"{t['term']}: {t['meaning']}") for t in result["terms"] if isinstance(t, dict)]
    return "\n".join(parts)


def file_summary_speech(result: Optional[Dict[str, Any]]) -> str:
    if not result or result.get("status") not in ("ok", "needs_review", "manual"):
        return ""
    lab = _labels(result.get("language"))
    return _sentence(f"{lab['file_manual' if result['status'] == 'manual' else 'file']} {result['summary']}")
