"""Spoken commands (Arabic / English) and the fixed order in which problems are reported.

The direction words are moves of the PHONE, not of the page: if the page shows on the right of
the frame, the phone must move right to centre it.
"""
from typing import Dict, Tuple

# key -> (Arabic, English): the short command that is spoken
COMMANDS: Dict[str, Tuple[str, str]] = {
    "find_page": ("وجّه الكاميرا نحو الورقة", "Point the camera at the page"),
    "too_dark": ("الإضاءة ضعيفة", "The light is too low"),
    "move_away": ("بعّد", "Move back"),
    "move_closer": ("قرّب", "Move closer"),
    "move_right": ("يمين", "Right"),
    "move_left": ("يسار", "Left"),
    "move_up": ("ارفع", "Up"),
    "move_down": ("نزّل", "Down"),
    "tilt": ("الموبايل مائل، خلّيه موازي للورقة", "The phone is tilted; hold it level with the page"),
    "glare": ("في انعكاس قوي، حرّك الموبايل قليلاً", "Strong glare; move the phone a little"),
    "hold_still": ("اثبت", "Hold still"),
    "ready": ("ممتاز، اثبت", "Good, hold still"),
    "captured": ("تم التصوير", "Photo taken"),
    "read_failed": ("ما قدرت أقرأ الورقة، جرّب تصوّر مرة ثانية", "I couldn't read the page; please take the photo again"),
}

# key -> (Arabic, English): why, for the app's screen and the logs (not spoken by default)
REASONS: Dict[str, Tuple[str, str]] = {
    "find_page": ("لم تُكتشف ورقة في اللقطة", "no page found in the frame"),
    "too_dark": ("اللقطة معتمة", "the frame is too dark"),
    "move_away": ("أطراف الورقة خارج اللقطة", "the page goes past the frame"),
    "move_closer": ("الورقة صغيرة في اللقطة", "the page is small in the frame"),
    "move_right": ("الورقة إلى يمين المنتصف", "the page is right of centre"),
    "move_left": ("الورقة إلى يسار المنتصف", "the page is left of centre"),
    "move_up": ("الورقة أعلى المنتصف", "the page is above centre"),
    "move_down": ("الورقة أسفل المنتصف", "the page is below centre"),
    "tilt": ("الورقة مائلة كثيراً في اللقطة", "the page is strongly tilted in the frame"),
    "glare": ("انعكاس ضوء قوي على الورقة", "strong light reflection on the page"),
    "hold_still": ("اللقطة غير واضحة (اهتزاز)", "the frame is blurred (shaking)"),
    "ready": ("كل الفحوصات ناجحة", "all checks pass"),
    "captured": ("كل الفحوصات بقيت ناجحة مدة كافية", "all checks passed long enough"),
    "read_failed": ("لم يُستخرج نص من الصورة", "no text could be read from the photo"),
}

# Fixed priority: the first failing check is the one command given.
# Light first (nothing else can be judged in the dark), then framing (cut edges, position,
# size), then the angle, glare and, last, sharpness (only worth fixing once the page is framed).
PRIORITY = ("find_page", "too_dark", "move_away", "move_right", "move_left", "move_up", "move_down",
            "move_closer", "tilt", "glare", "hold_still")


def say(key: str, mode: str) -> str:
    return COMMANDS[key][1 if mode == "en" else 0]


def reason(key: str, mode: str) -> str:
    return REASONS[key][1 if mode == "en" else 0]
