"""Test setup: isolated environment, a fixed "now", and small generated lecture files."""
import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT.parent / "document-reader" / "src"))

AMMAN = timezone(timedelta(hours=3))
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=AMMAN)          # Wednesday 18 November 2026, noon


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    import os
    for k in [k for k in os.environ if k.startswith(("READER_", "NARRATOR_"))
              or k in ("GEMINI_API_KEY", "CB_EXPLAIN_LANGUAGE")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("READER_IMAGES_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("READER_DESCRIPTIONS_DIR", str(tmp_path / "descriptions"))
    monkeypatch.setenv("READER_ENV_FILE", str(tmp_path / "no.env"))     # never the real key
    monkeypatch.setenv("READER_OCR_DIR", str(tmp_path / "ocr"))

    def no_network(*args, **kwargs):
        raise AssertionError("test tried to reach Gemini; inject a fake vision engine")
    from google import genai
    monkeypatch.setattr(genai, "Client", no_network)


def config(language="mixed", **kw):
    from narrator import NarratorConfig
    return NarratorConfig(language=language, **kw).validate()


def png(width=200, height=120, color=(30, 120, 200)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def lecture(tmp_path):
    """3 slides: an intro, a table of 5 rows, and a picture (same topic as slide 2)."""
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = "مقدمة"
    s1.placeholders[1].text = "نتعلم اليوم توزيع المعاينة."
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Sampling"
    rows = [["Sample", "Mean", "Size"], ["A", "71", "36"], ["B", "73", "36"], ["C", "72", "30"],
            ["D", "70", "40"], ["E", "74", "50"]]
    table = s2.shapes.add_table(len(rows), 3, Inches(1), Inches(2), Inches(6), Inches(3)).table
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    s3 = prs.slides.add_slide(prs.slide_layouts[5])
    s3.shapes.title.text = "Sampling"
    pic = tmp_path / "curve.png"
    pic.write_bytes(png())
    s3.shapes.add_picture(str(pic), Inches(2), Inches(2), Inches(3), Inches(2))
    path = tmp_path / "lecture.pptx"
    prs.save(str(path))
    return path


@pytest.fixture
def three_slides_with_images(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    for i, color in enumerate([(200, 0, 0), (0, 150, 0), (0, 0, 200)], 1):
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = f"Slide {i}"
        pic = tmp_path / f"p{i}.png"
        pic.write_bytes(png(color=color))
        slide.shapes.add_picture(str(pic), Inches(2), Inches(2), Inches(3), Inches(2))
    path = tmp_path / "images.pptx"
    prs.save(str(path))
    return path


class FakeVision:
    model = "fake-vision"

    def __init__(self, answer):
        self.answer = answer

    def describe(self, image, mime, prompt, schema):
        return dict(self.answer)


def fake_describer(answer, language="mixed"):
    from reader import ImageDescriber, ReaderConfig
    return ImageDescriber(ReaderConfig.from_env(), engine=FakeVision(answer), language=language)
