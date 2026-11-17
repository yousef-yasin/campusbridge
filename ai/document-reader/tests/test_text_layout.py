from reader.lang import clean_text, detect_language, fix_visual_order, is_visual_order
from reader.layout import order_boxes, split_columns
from reader.tables import make_table, table_text


def test_detect_language():
    assert detect_language("مقدمة في الذكاء الاصطناعي") == "ar"
    assert detect_language("Introduction to machine learning") == "en"
    assert detect_language("اليوم سنتحدث عن machine learning") == "mixed"
    long_ar = "هذه جملة عربية طويلة جدا فيها كلمات كثيرة تشرح الموضوع بالتفصيل الكامل للطلاب " * 2
    assert detect_language(long_ar + "Python") == "ar"            # one term in a long text
    assert detect_language("123 - 456") is None and detect_language("") is None


def test_clean_text_normalizes_arabic_presentation_forms_and_invisible_marks():
    # 'مقدمة' as stored by many PDFs (presentation forms), with bidi marks and tatweel
    assert clean_text("ﻣﻘﺪﻣﺔ‏  ـالفصل­\n\n") == "مقدمة الفصل"
    assert clean_text("ﻻ") == "لا"                                # lam-alef ligature
    assert clean_text("ﬁle") == "file"                            # Latin ligature
    assert clean_text(" item") == "item"                         # private-use bullet glyph
    assert clean_text("x² + H₂O") == "x² + H₂O"                         # other characters untouched


def test_visual_order_arabic_is_repaired():
    logical = "ﻣﺮﺣﺒﺎ"            # مرحبا in logical order (presentation forms)
    visual = logical[::-1]                                 # stored as drawn, right to left
    assert not is_visual_order(logical) and is_visual_order(visual)
    assert clean_text(fix_visual_order(visual)) == "مرحبا"
    # drawn left to right as "AI 2024 <Arabic reversed>": logically the Arabic comes first and the
    # English run keeps its own left-to-right order
    assert clean_text(fix_visual_order(f"AI 2024 {visual}")) == "مرحبا AI 2024"
    assert fix_visual_order("plain English text") == "plain English text"


def test_order_boxes_columns_and_rtl():
    title = ((50, 10, 550, 40), "title")
    right = ((320, 60, 550, 300), "right column")
    left = ((50, 60, 280, 300), "left column")
    footer = ((50, 320, 550, 340), "footer")
    items = [left, footer, right, title]
    assert order_boxes(items, rtl=True) == ["title", "right column", "left column", "footer"]
    assert order_boxes(items, rtl=False) == ["title", "left column", "right column", "footer"]
    same_line = [((10, 0, 50, 10), "a"), ((60, 1, 100, 11), "b")]
    assert order_boxes(same_line, rtl=True) == ["b", "a"]
    assert len(split_columns([((0, 0, 10, 10), 1), ((40, 0, 50, 10), 2)], gap=20)) == 2
    assert len(split_columns([((0, 0, 10, 10), 1), ((15, 0, 50, 10), 2)], gap=20)) == 1


def test_tables_to_readable_rows():
    table = make_table([["الاسم", "الدرجة", ""], ["أحمد", 90.0, None], [None, None, None], ["سارة", "", ""]])
    assert table["columns"] == ["الاسم", "الدرجة", "3"]
    assert table_text(table) == "الاسم: أحمد، الدرجة: 90\nالاسم: سارة"
    english = make_table([["Model", "Accuracy"], ["CNN", "92"]])
    assert table_text(english) == "Model: CNN; Accuracy: 92"
    assert table_text(make_table([["Only", "header"]])) == "Only; header"
    assert make_table([[None, ""], []]) is None
