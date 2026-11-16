from tts.text import (clean, detect_language, expand, number_to_words, prepare, split_by_language,
                      split_sentences)


def pairs(segments):
    return [(s.lang, s.text) for s in segments]


def test_clean_unifies_digits_whitespace_and_tatweel():
    assert clean("  الســلام   عليكم \n\n  ٣ طلاب ") == "السلام عليكم\n3 طلاب"
    assert clean("۱۲٫٥") == "12.5"


def test_split_sentences_on_arabic_and_latin_punctuation():
    text = "مرحبا بكم. كيف الحال؟ هذا سطر\nسطر جديد! السعر 3.5 دينار."
    assert split_sentences(text) == ["مرحبا بكم.", "كيف الحال؟", "هذا سطر", "سطر جديد!",
                                     "السعر 3.5 دينار."]


def test_long_sentence_is_wrapped_at_commas_then_words():
    sentence = "الجزء الأول من الجملة، الجزء الثاني من الجملة، الجزء الثالث من الجملة"
    parts = split_sentences(sentence, max_chars=30)
    assert len(parts) == 3 and all(len(p) <= 30 for p in parts)
    words = split_sentences("كلمة " * 20, max_chars=22)
    assert all(len(p) <= 22 for p in words) and " ".join(words).split() == ["كلمة"] * 20


def test_detect_language_by_dominant_script():
    assert detect_language("اليوم نتحدث عن الخوارزميات") == "ar"
    assert detect_language("Today we discuss algorithms") == "en"
    assert detect_language("نستخدم Python في المشروع") == "ar"
    assert detect_language("The word كتاب means book") == "en"
    assert detect_language("عندنا 3 مواضيع عن machine learning.") == "ar"   # words, not letters
    assert detect_language("مرحبا Hello") == "ar" and detect_language("مرحبا Hello", "en") == "en"
    assert detect_language("123 ...") == "ar"
    assert detect_language("123", fallback="en") == "en"


def test_numbers_to_words_in_both_languages():
    assert number_to_words("5", "ar") == "خمسة"
    assert number_to_words("21", "ar") == "واحد وعشرون"
    assert number_to_words("21", "en") == "twenty-one"
    assert number_to_words("1,250", "en") == "one thousand, two hundred and fifty"
    assert number_to_words("3.5", "ar") == "ثلاثة فاصلة خمسة"
    assert number_to_words("3.25", "en") == "three point two five"
    assert number_to_words("40%", "ar") == "أربعون بالمئة"
    assert number_to_words("40%", "en") == "forty percent"
    assert number_to_words("079", "en") == "zero seven nine"


def test_expand_numbers_and_symbols_follow_sentence_language():
    assert expand("عندي 3 أسئلة.", "ar") == "عندي ثلاثة أسئلة."
    assert expand("I have 3 questions.", "en") == "I have three questions."
    assert expand("2 + 2 = 4", "en") == "two plus two equals four"
    assert expand("COVID19", "en") == "COVID nineteen"


def test_split_by_language_keeps_punctuation_with_previous_run():
    assert pairs(split_by_language("استخدمنا Python في المشروع.", "ar")) == [
        ("ar", "استخدمنا"), ("en", "Python"), ("ar", "في المشروع.")]
    assert pairs(split_by_language("بالPython", "ar")) == [("ar", "بال"), ("en", "Python")]
    assert pairs(split_by_language("...", "ar")) == [("ar", "...")]


def test_prepare_auto_detects_language_per_sentence():
    segs = prepare("مرحبا بكم. Welcome to the lecture. شكرا")
    assert pairs(segs) == [("ar", "مرحبا بكم."), ("en", "Welcome to the lecture."), ("ar", "شكرا")]


def test_prepare_auto_splits_mixed_sentence_and_numbers_use_sentence_language():
    segs = prepare("اليوم عندنا 3 محاضرات عن machine learning و 2 عن الشبكات.")
    assert pairs(segs) == [("ar", "اليوم عندنا ثلاثة محاضرات عن"), ("en", "machine learning"),
                           ("ar", "و اثنان عن الشبكات.")]
    segs = prepare("We have 3 lectures about الذكاء الاصطناعي today.")
    assert pairs(segs) == [("en", "We have three lectures about"), ("ar", "الذكاء الاصطناعي"),
                           ("en", "today.")]


def test_prepare_manual_language_uses_one_voice():
    segs = prepare("استخدمنا Python 3 مرات. Thank you.", language="ar")
    assert pairs(segs) == [("ar", "استخدمنا Python ثلاثة مرات."), ("ar", "Thank you.")]
    segs = prepare("عندي 2 questions", language="en")
    assert pairs(segs) == [("en", "عندي two questions")]


def test_prepare_drops_unspeakable_text():
    assert prepare("") == []
    assert prepare("  ... !!! \n ؟ ") == []
    assert pairs(prepare("٥")) == [("ar", "خمسة")]
