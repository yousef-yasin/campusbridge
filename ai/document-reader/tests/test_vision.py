"""Phase 2: image descriptions with a fake vision engine, and native charts (no AI)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import png
from reader import (ConfigError, ImageDescriber, VisionError, VisionQuotaError, VisionUnavailableError,
                    explain_language, open_document, to_speech_text)
from reader.__main__ import main
from reader.describe import PROMPT_VERSION
from reader.explain import INSTRUCTIONS
from reader.vision import GeminiVision

PHOTO = {"category": "photo", "short_description": "صورة توضح Supervised Learning (التعلم الموجه).",
         "detailed_description": "وصف مفصل للصورة.", "text_in_image": "", "photo": {"role": "مثال"}}


class FakeVision:
    """Stands in for GeminiVision: returns prepared answers and records each request."""
    model = "fake-vision"

    def __init__(self, *answers, errors=()):
        self.answers = list(answers) or [PHOTO]
        self.errors = list(errors)
        self.calls = []

    def describe(self, image, mime, prompt, schema):
        self.calls.append({"prompt": prompt, "mime": mime, "size": len(image), "schema": schema})
        if self.errors:
            error = self.errors.pop(0)
            if error is not None:
                raise error
        answer = self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]
        return dict(answer)


def first_image(page):
    return next(b for b in page.blocks if b.kind == "image")


@pytest.fixture
def three_images(tmp_path):
    """Slides with three different pictures and a title each."""
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    for i, color in enumerate([(200, 0, 0), (0, 150, 0), (0, 0, 200)], 1):
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = f"Slide {i}"
        pic = tmp_path / f"p{i}.png"
        pic.write_bytes(png(220, 160, color))
        slide.shapes.add_picture(str(pic), Inches(2), Inches(2), Inches(3), Inches(2))
    path = tmp_path / "three.pptx"
    prs.save(str(path))
    return path


# --- describing -----------------------------------------------------------------------

def test_image_is_described_with_page_context_and_mixed_language(pptx_file, cfg):
    engine = FakeVision()
    with open_document(pptx_file, cfg) as doc:
        page = doc.page(2)
        warnings = ImageDescriber(cfg, engine=engine).describe_pages([page])
    image = first_image(page).image
    assert warnings == [] and len(engine.calls) == 1
    assert (image["status"], image["category"], image["language"]) == ("described", "photo", "mixed")
    assert image["description"] == PHOTO["short_description"] and image["details"] == "وصف مفصل للصورة."
    prompt = engine.calls[0]["prompt"]
    assert "أنواع التعلم" in prompt                       # slide title
    assert "التعلم الموجه supervised" in prompt           # text around the image
    assert INSTRUCTIONS["mixed"] in prompt and "original" in prompt and "language and script" in prompt
    assert engine.calls[0]["mime"] == "image/png"
    assert engine.calls[0]["schema"]["properties"]["category"]["enum"][-1] == "decorative"


def test_three_language_modes_shared_setting(pptx_file, cfg, monkeypatch):
    prompts = {}
    for mode in ("ar", "en", "mixed"):
        engine = FakeVision()
        with open_document(pptx_file, cfg) as doc:
            ImageDescriber(cfg, engine=engine, language=mode).describe_pages([doc.page(2)])
        prompts[mode] = engine.calls[0]["prompt"]
    for mode, prompt in prompts.items():
        assert INSTRUCTIONS[mode] in prompt and all(INSTRUCTIONS[m] not in prompt for m in prompts if m != mode)
    files = sorted(p.name for p in Path(cfg.descriptions_dir).iterdir())
    assert len(files) == 3 and all(f"__v{PROMPT_VERSION}.json" in f for f in files)   # one cache entry per mode
    monkeypatch.setenv("CB_EXPLAIN_LANGUAGE", "en")
    assert explain_language() == "en" and explain_language("ar") == "ar"
    monkeypatch.setenv("CB_EXPLAIN_LANGUAGE", "fr")
    with pytest.raises(ConfigError):
        explain_language()


def test_cache_is_reused_and_a_manual_description_wins(pptx_file, cfg):
    engine = FakeVision()
    with open_document(pptx_file, cfg) as doc:
        ImageDescriber(cfg, engine=engine).describe_pages([doc.page(2)])
        page = doc.page(2)
        describer = ImageDescriber(cfg, engine=engine)
        describer.describe_pages([page])
        assert len(engine.calls) == 1 and describer.calls == 0          # second run: from the cache
        assert "وصف تلقائي: صورة توضح Supervised Learning (التعلم الموجه)." in to_speech_text(page)[0].text
        path = describer.cache_path(first_image(page).image["sha256"])
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["result"]["category"] == "photo" and record["manual"]["short"] == ""
        assert (record["model"], record["language"], record["prompt_version"]) == ("fake-vision", "mixed", PROMPT_VERSION)
        record["manual"]["short"] = "مخطط يقارن نوعي التعلم."
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        page = doc.page(2)
        ImageDescriber(cfg, engine=engine).describe_pages([page])
        image = first_image(page).image
        assert image["status"] == "manual" and image["description"] == "مخطط يقارن نوعي التعلم."
        speech = to_speech_text(page)[0].text
        assert "صورة: مخطط يقارن نوعي التعلم." in speech and "وصف تلقائي" not in speech
        other_model = FakeVision()
        other_model.model = "another-model"
        ImageDescriber(cfg, engine=other_model).describe_pages([doc.page(2)])
        assert len(other_model.calls) == 1                              # model is part of the cache key


def test_each_category_is_read_aloud_its_own_way(three_images, cfg):
    table = {"category": "table", "short_description": "جدول يقارن النماذج.", "detailed_description": "...",
             "text_in_image": "Model Accuracy CNN 92", "table": {"columns": ["Model", "Accuracy"],
                                                                 "rows": [["CNN", "92"], ["SVM", "85"]]}}
    equation = {"category": "equation", "short_description": "z تساوي x ناقص μ مقسومة على σ.",
                "detailed_description": "تفصيل المعادلة.", "text_in_image": "z = (x - μ) / σ",
                "equation": {"written": "z = (x - μ) / σ", "spoken": "z تساوي x ناقص μ مقسومة على σ"}}
    decorative = {"category": "decorative", "short_description": "زخرفة.", "detailed_description": "",
                  "text_in_image": ""}
    engine = FakeVision(table, equation, decorative)
    with open_document(three_images, cfg) as doc:
        pages = list(doc.pages())
        ImageDescriber(cfg, engine=engine).describe_pages(pages)
    speech = [u.text for u in to_speech_text(pages)]
    assert "وصف تلقائي: جدول يقارن النماذج.\nModel: CNN; Accuracy: 92.\nModel: SVM; Accuracy: 85." in speech[0]
    assert first_image(pages[0]).image["table"]["rows"] == [["CNN", "92"], ["SVM", "85"]]
    assert "وصف تلقائي: z تساوي x ناقص μ مقسومة على σ." in speech[1]
    assert first_image(pages[1]).image["text"] == "z = (x - μ) / σ"          # kept as written
    assert speech[2] == "Slide 3."                                          # decorative: skipped
    detailed = to_speech_text(pages[1], detailed_images=True)[0].text
    assert "وصف تلقائي: تفصيل المعادلة." in detailed


def test_image_limit_per_run_and_cached_images_do_not_count(three_images, cfg):
    cfg.vision_max_images = 2
    engine = FakeVision()
    with open_document(three_images, cfg) as doc:
        pages = list(doc.pages())
        warnings = ImageDescriber(cfg, engine=engine).describe_pages(pages)
        assert len(engine.calls) == 2
        assert [first_image(p).image["status"] for p in pages] == ["described", "described", "undescribed"]
        assert "limit of 2" in first_image(pages[2]).image["reason"] and "READER_VISION_MAX_IMAGES" in warnings[0]
        assert to_speech_text(pages[2])[0].text.endswith("صورة بدون وصف.")
        cfg.vision_max_images = 1
        pages = list(doc.pages())
        ImageDescriber(cfg, engine=engine).describe_pages(pages)        # 2 cached + 1 new call
    assert len(engine.calls) == 3 and all(first_image(p).image["status"] == "described" for p in pages)


# --- numbers in a description must be in the image -------------------------------------

def test_a_calculated_number_marks_the_description_needs_review(three_images, cfg):
    # Real case, CLT slide 16 in "ar": the image says 95.4% and the model wrote 94% (in words).
    chart = {"category": "chart",
             "short_description": "رسم بياني يوضح المنحنى الطبيعي ونسب المساحات تحته.",
             "detailed_description": ("يقع 34.1% من البيانات بين المتوسط وانحراف معياري واحد. "
                                      "ويقع أربعة وتسعون بالمائة من البيانات ضمن انحرافين معياريين."),
             "text_in_image": "-3σ -2σ -1σ M 1σ 2σ 3σ 0.1% 2.1% 13.6% 34.1% 34.1% 13.6% 2.1% 0.1% 95.4%",
             "chart": {"chart_type": "normal curve", "key_values": ["34.1%", "13.6%"], "trend": ""}}
    good = dict(chart, detailed_description="يقع 95.4% من البيانات ضمن انحرافين معياريين، و 34.1% بين "
                                            "المتوسط وانحراف معياري واحد، في ثلاث مناطق.")
    engine = FakeVision(chart, good)
    with open_document(three_images, cfg) as doc:
        pages = [doc.page(1), doc.page(2)]
        describer = ImageDescriber(cfg, engine=engine, language="ar")
        warnings = describer.describe_pages(pages)
    bad, ok = first_image(pages[0]).image, first_image(pages[1]).image
    assert "never write numbers in words" in engine.calls[0]["prompt"] and "Never calculate" in engine.calls[0]["prompt"]
    assert bad["status"] == "needs_review" and bad["unverified_numbers"] == ["94"]
    assert ok["status"] == "described" and "unverified_numbers" not in ok      # 95.4 matches, 3 is a count
    assert any("94" in w and "needs_review" in w for w in warnings)
    record = json.loads(describer.cache_path(bad["sha256"]).read_text(encoding="utf-8"))
    assert record["number_check"] == {"needs_review": True, "unverified_numbers": ["94"]}

    detailed = to_speech_text(pages[0], detailed_images=True)[0].text
    assert "أربعة وتسعون" not in detailed                                  # the wrong sentence is dropped
    assert "وصف تلقائي: يقع 34.1% من البيانات بين المتوسط وانحراف معياري واحد." in detailed
    assert "الأرقام كما وردت في الصورة: -3σ -2σ" in detailed and "95.4%" in detailed
    short = to_speech_text(pages[0])[0].text
    assert "وصف تلقائي: رسم بياني يوضح المنحنى الطبيعي" in short and "الأرقام كما وردت في الصورة:" in short

    with open_document(three_images, cfg) as doc:                             # from the cache, same result
        page = doc.page(1)
        ImageDescriber(cfg, engine=engine, language="ar").describe_pages([page])
    assert first_image(page).image["status"] == "needs_review" and len(engine.calls) == 2


def test_number_matching_rules():
    from reader.numbers import numbers_in, unverified_numbers
    assert numbers_in("أربعة وتسعون بالمائة") == ["94"]
    assert numbers_in("خمسة وتسعون فاصلة أربعة") == ["95.4"]
    old = ("ثمانية وستون بالمائة تقريبا بين سالب واحد وموجب واحد، وأربعة وتسعون بالمائة تقريبا بين "
           "سالب اثنين وموجب اثنين، وتسعة وتسعون بالمائة")                # the real "ar" answer
    assert numbers_in(old) == ["68", "1", "1", "94", "2", "2", "99"]
    assert numbers_in("مائة وخمسة وعشرون، وثلاثة عشر") == ["125", "13"]
    assert numbers_in("ninety-four percent, two hundred and five") == ["94", "205"]
    assert numbers_in("1,000 و .9713 و 95.40% و ٣٤٫١") == ["1000", "0.9713", "95.4", "34.1"]
    assert unverified_numbers(["68% و 95.4% و 99.7%"], ["68.27% 95.45% 99.73%"]) == ["68", "95.4", "99.7"]
    assert unverified_numbers(["أربعة أنواع و 3 منحنيات"], [""]) == []        # counts up to 10
    assert unverified_numbers(["لعام 2022"], ["", "Global cancer burden 2022"]) == []   # page text


# --- failures never stop the reader ----------------------------------------------------

def test_quota_error_stops_further_calls_and_marks_images(three_images, cfg):
    cfg.vision_retry_wait = 0
    engine = FakeVision(errors=[VisionQuotaError("Gemini quota or rate limit exceeded (429): RESOURCE_EXHAUSTED")])
    with open_document(three_images, cfg) as doc:
        pages = list(doc.pages())
        warnings = ImageDescriber(cfg, engine=engine).describe_pages(pages)
    assert len(engine.calls) == 1
    assert all(first_image(p).image["status"] == "undescribed" for p in pages)
    assert "429" in warnings[0] and "stopped" in warnings[0]


def test_busy_service_skips_the_image_and_stops_after_three_in_a_row(three_images, cfg, tmp_path):
    from reader import VisionBusyError
    busy = lambda: VisionBusyError("Gemini service error (503): high demand")
    engine = FakeVision(errors=[busy(), None, busy()])
    with open_document(three_images, cfg) as doc:
        pages = list(doc.pages())
        warnings = ImageDescriber(cfg, engine=engine).describe_pages(pages)
    assert [first_image(p).image["status"] for p in pages] == ["undescribed", "described", "undescribed"]
    assert len(engine.calls) == 3 and "overloaded" in warnings[0] and "run again later" in warnings[0]
    cfg.descriptions_dir = str(tmp_path / "fresh")
    engine = FakeVision(errors=[busy(), busy(), busy()])
    with open_document(three_images, cfg) as doc:
        pages = list(doc.pages())
        warnings = ImageDescriber(cfg, engine=engine).describe_pages(pages)
    assert len(engine.calls) == 3 and any("3 images in a row" in w for w in warnings)


def test_short_rate_limit_is_retried_once(three_images, cfg):
    cfg.vision_retry_wait = 1
    engine = FakeVision(errors=[VisionQuotaError("429", retry_after=0.01), None])
    with open_document(three_images, cfg) as doc:
        page = doc.page(1)
        ImageDescriber(cfg, engine=engine).describe_pages([page])
    assert len(engine.calls) == 2 and first_image(page).image["status"] == "described"


def test_missing_key_marks_images_without_reaching_google(pptx_file, cfg, capsys):
    with open_document(pptx_file, cfg) as doc:
        page = doc.page(2)
        warnings = ImageDescriber(cfg).describe_pages([page])            # real engine, no key
    image = first_image(page).image
    assert image["status"] == "undescribed" and "GEMINI_API_KEY is not set" in image["reason"]
    assert "GEMINI_API_KEY is not set" in warnings[0]
    assert main(["extract", str(pptx_file), "--page", "2", "--describe"]) == 0       # CLI keeps going
    captured = capsys.readouterr()
    assert "status: undescribed" in captured.out and "GEMINI_API_KEY is not set" in captured.err


def test_gemini_errors_are_mapped_and_the_key_is_scrubbed(cfg, tmp_path):
    secret = "FAKE-TEST-KEY-NOT-REAL"
    (tmp_path / "test.env").write_text(f"GEMINI_API_KEY={secret}\n", encoding="utf-8")

    class Client:
        def __init__(self, error=None, text=None):
            self.error, self.text, self.request = error, text, None
            self.models = self

        def generate_content(self, model, contents, config):
            self.request = {"model": model, "contents": contents, "config": config}
            if self.error:
                raise self.error
            return SimpleNamespace(text=self.text)

    class ApiError(Exception):
        def __init__(self, code, message):
            super().__init__(message)
            self.code, self.message = code, message

    ok = Client(text=json.dumps(PHOTO, ensure_ascii=False))
    assert GeminiVision(cfg, client=ok).describe(png(60, 60), "image/png", "prompt", {"type": "object"}) == PHOTO
    assert ok.request["model"] == "gemini-3.5-flash-lite"
    assert ok.request["config"].response_mime_type == "application/json"
    assert [p.text is not None for p in ok.request["contents"]] == [True, False]   # prompt, then image
    for error, kind in ((ApiError(429, "RESOURCE_EXHAUSTED"), VisionQuotaError),
                        (ApiError(403, "PERMISSION_DENIED"), VisionUnavailableError),
                        (OSError("network down"), VisionUnavailableError),
                        (ApiError(400, f"bad request with key {secret}"), VisionError)):
        with pytest.raises(kind) as err:
            GeminiVision(cfg, client=Client(error=error)).describe(b"x", "image/png", "p", {})
        assert secret not in str(err.value)
    with pytest.raises(VisionError, match="no valid JSON"):
        GeminiVision(cfg, client=Client(text="not json")).describe(b"x", "image/png", "p", {})


def test_busy_server_is_retried_then_asked_without_the_schema(cfg):
    class Busy(Exception):
        code = 503

    class Client:
        def __init__(self):
            self.models, self.schemas = self, []

        def generate_content(self, model, contents, config):
            self.schemas.append(config.response_json_schema)
            if len(self.schemas) < 3:
                raise Busy("503 UNAVAILABLE: high demand")
            return SimpleNamespace(text=json.dumps(PHOTO, ensure_ascii=False))

    client = Client()
    engine = GeminiVision(cfg, client=client)
    engine.retry_pauses = (0, 0)
    schema = {"type": "object", "required": ["category"]}
    assert engine.describe(png(60, 60), "image/png", "p", schema)["category"] == "photo"
    assert client.schemas == [schema, schema, None]           # last try: plain JSON, no schema

    always_busy = Client()
    always_busy.generate_content = lambda **kw: (_ for _ in ()).throw(Busy("503"))
    engine = GeminiVision(cfg, client=always_busy)
    engine.retry_pauses = (0, 0)
    from reader import VisionBusyError
    with pytest.raises(VisionBusyError, match="503"):
        engine.describe(b"x", "image/png", "p", schema)


def test_unreadable_image_file_is_marked_not_sent(pptx_file, cfg):
    engine = FakeVision()
    with open_document(pptx_file, cfg) as doc:
        page = doc.page(2)
    path = first_image(page).image["path"]
    open(path, "wb").write(b"not an image")
    ImageDescriber(cfg, engine=engine).describe_pages([page])
    assert engine.calls == [] and "format not supported" in first_image(page).image["reason"]


# --- native charts: data read from the file, no AI ------------------------------------

def test_native_pptx_chart_is_read_without_ai(tmp_path, cfg):
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "نتائج الطلاب"
    data = CategoryChartData()
    data.categories = ["أحمد", "سارة", "عمر"]
    data.add_series("الرياضيات", (80, 95, 60))
    frame = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(2), Inches(6), Inches(4), data)
    frame.chart.has_title = True
    frame.chart.chart_title.text_frame.text = "علامات الرياضيات"
    prs.save(str(tmp_path / "chart.pptx"))
    with open_document(tmp_path / "chart.pptx", cfg) as doc:
        page = doc.page(1)
        info = doc.info
    chart = next(b for b in page.blocks if b.kind == "chart")
    assert chart.chart["type"] == "bar" and chart.chart["categories"] == ["أحمد", "سارة", "عمر"]
    assert chart.chart["series"] == [{"name": "الرياضيات", "values": ["80", "95", "60"]}]
    assert chart.text.split("\n") == ["مخطط أعمدة بعنوان «علامات الرياضيات»", "الرياضيات: أحمد 80، سارة 95، عمر 60"]
    assert info.chart_count == 1 and not any("chart" in w for w in info.warnings)
    assert "الرياضيات: أحمد 80، سارة 95، عمر 60." in to_speech_text(page)[0].text
