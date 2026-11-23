"""Answers as text for text-to-speech, and the fixed messages."""
from typing import Any, Dict

from cb_shared import AILimitError, AIQuotaError

NOT_FOUND = {"ar": "هذا غير موجود في محاضرات المساق.",          # STU-20
             "en": "This is not in the course lectures."}
LABEL = {"ar": "جواب تلقائي:", "en": "Automatic answer:"}
SOURCES = {"ar": "المصادر:", "en": "Sources:"}
GLOSSARY = {"ar": "القاموس المشترك", "en": "the course glossary"}
UNITS = {"ar": {"slide": "سلايد", "page": "صفحة", "sheet": "ورقة", "part": "جزء"},
         "en": {"slide": "slide", "page": "page", "sheet": "sheet", "part": "part"}}
REVIEW = {"ar": "قد يحتاج هذا الجواب إلى مراجعة.", "en": "This answer may need checking."}


def _key(mode: str) -> str:
    return "en" if mode == "en" else "ar"


def source_label(source: Dict[str, Any], mode: str) -> str:
    k = _key(mode)
    if source.get("type") == "glossary":
        return GLOSSARY[k]
    unit = UNITS[k].get(source.get("unit_type"), source.get("unit_type", ""))
    sep = "، " if k == "ar" else ", "
    return f"{source.get('file')}{sep}{unit} {source.get('unit')}"


def unavailable_message(exc: Exception, mode: str) -> str:
    """A clear message for the student when the AI service cannot answer (never a crash)."""
    k = _key(mode)
    text = str(exc)
    if isinstance(exc, AILimitError):
        why = {"ar": "وصل عدد طلبات الذكاء الاصطناعي إلى الحد المسموح", "en": "the AI request limit was reached"}
    elif isinstance(exc, AIQuotaError) or "429" in text:
        why = {"ar": "انتهت حصة الطلبات المجانية حالياً", "en": "the free request quota is used up for now"}
    elif "API_KEY" in text or "API key" in text:
        why = {"ar": "مفتاح خدمة الذكاء الاصطناعي غير مضبوط", "en": "the AI service key is not set"}
    elif "unreachable" in text or "internet" in text:
        why = {"ar": "لا يوجد اتصال بالإنترنت", "en": "there is no internet connection"}
    elif "busy" in text or "503" in text or "service error" in text or "no answer" in text:
        why = {"ar": "خدمة الذكاء الاصطناعي مشغولة الآن", "en": "the AI service is busy"}
    else:
        why = {"ar": "حدث خطأ في خدمة الذكاء الاصطناعي", "en": "the AI service failed"}
    if k == "en":
        return f"The assistant cannot answer now: {why['en']}. Please try again later."
    return f"المساعد لا يستطيع الإجابة الآن: {why['ar']}. جرّب مرة ثانية بعد قليل."


def answer_speech(answer, mode: str) -> str:
    """«جواب تلقائي: ...» then the sources. Messages (not found, unavailable) are read as they are."""
    k = _key(mode)
    if answer.status in ("unavailable", "clarify"):
        return answer.answer
    import re
    text = re.sub(r"\s*\[[^\[\]]*\]", "", answer.answer).strip()
    parts = [f"{LABEL[k]} {text}"]
    if answer.status == "needs_review":
        parts.append(REVIEW[k])
    labels = spoken_sources(answer.sources, mode)
    if labels and answer.status != "not_found":
        parts.append(f"{SOURCES[k]} {('، ' if k == 'ar' else ', ').join(labels)}.")
    return " ".join(parts)


UNITS_PLURAL = {"ar": {"slide": "سلايدات", "page": "صفحات", "sheet": "أوراق", "part": "أجزاء"},
                "en": {"slide": "slides", "page": "pages", "sheet": "sheets", "part": "parts"}}


def spoken_sources(sources, mode: str):
    """Sources for listening: one entry per file, its title rather than its file name, units in
    order: «Chapter 1 - Information Security، صفحات 4 و5 و6»."""
    k = _key(mode)
    groups: Dict[str, Dict[str, Any]] = {}
    out = []
    for s in sources:
        if s.get("type") == "glossary":
            out.append(GLOSSARY[k])
            continue
        g = groups.setdefault(s.get("file"), {"name": s.get("file_title") or s.get("file"),
                                              "type": s.get("unit_type"), "units": []})
        if s.get("unit") not in g["units"]:
            g["units"].append(s.get("unit"))
    for g in groups.values():
        units = sorted(u for u in g["units"] if u is not None)
        word = (UNITS_PLURAL if len(units) > 1 else UNITS)[k].get(g["type"], g["type"] or "")
        joined = (" و" if k == "ar" else ", ").join(str(u) for u in units)
        if k == "en" and len(units) > 1:
            joined = ", ".join(str(u) for u in units[:-1]) + f" and {units[-1]}"
        out.append(f"{g['name']}{'، ' if k == 'ar' else ', '}{word} {joined}")
    return list(dict.fromkeys(out))
