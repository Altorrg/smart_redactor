"""Only synthetic fixtures. No private document is opened by these tests."""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unicodedata

import fitz
import pytest
from PIL import Image, ImageFont, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("PDF_REDACTOR_TESSERACT_PATH", "C:/Program Files/PDF24/tesseract/tesseract.exe")
os.environ.setdefault("PDF_REDACTOR_TESSDATA_PATH", str(ROOT / "tools/tessdata"))
import app
import redactor
from nlp_engine import find_sensitive_entities

OUT = ROOT / ".review/fixtures"
OUT.mkdir(parents=True, exist_ok=True)
FONT = Path("C:/Windows/Fonts/arial.ttf")
pdfmetrics.registerFont(TTFont("FixtureArial", str(FONT)))
LINES = ["SYNTHETIC TEST - NOT A REAL DOCUMENT", "Kovács Ágnes", "Őri Zsófia", "Árvíztűrő Építő Kft.", "Székesfehérvár", "1 250 000 Ft", "123,45 EUR", "KEEP THIS REFERENCE 987654"]
APPROVED = ["Kovács Ágnes", "Őri Zsófia", "Árvíztűrő Építő Kft.", "Székesfehérvár", "1 250 000 Ft", "123,45 EUR"]

def native(path: Path, lines=LINES):
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    c.setFont("FixtureArial", 16)
    for n, line in enumerate(lines):
        c.drawString(45, 790 - n * 43, line)
    c.save()
    return path

def scan(path: Path, *, mixed=False):
    image = Image.new("RGB", (1500, 2100), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), 40)
    for n, line in enumerate(LINES):
        draw.text((100, 100 + n * 115), line, font=font, fill="black")
    with fitz.open() as d:
        p = d.new_page(width=595, height=842)
        png = io.BytesIO(); image.save(png, "PNG")
        p.insert_image(p.rect, stream=png.getvalue())
        if mixed:
            p.insert_text((20, 825), "Native heading does not cover the scanned body")
        d.save(path)
    return path

@pytest.fixture(scope="module")
def documents():
    return {"native": native(OUT/"synthetic_native.pdf"), "scan": scan(OUT/"synthetic_scan.pdf"), "mixed": scan(OUT/"synthetic_mixed.pdf", mixed=True)}

@pytest.mark.parametrize("value", APPROVED)
def test_hungarian_candidates(value):
    assert value in {e["text"] for e in find_sensitive_entities("\n".join(LINES))}

def test_names_do_not_merge_across_lines():
    assert [x["text"] for x in find_sensitive_entities("Kovács Ágnes\nŐri Zsófia")] == ["Kovács Ágnes", "Őri Zsófia"]

def test_unicode_normalization_and_duplicates():
    hits = find_sensitive_entities(unicodedata.normalize("NFD", "Kovács Ágnes") + "\nKOVÁCS ÁGNES")
    assert len(hits) == 1 and hits[0]["occurrences"] == 2

def test_ocr_keeps_accent_and_decimal_identity():
    assert redactor._normalize_ocr_token("Őri") != redactor._normalize_ocr_token("Óri")
    assert redactor._normalize_ocr_token("123,45") != redactor._normalize_ocr_token("12,345")

def test_ocr_runtime_languages():
    status = redactor.configure_ocr_runtime()
    assert status["ready"], status
    assert {"hun", "eng"} <= set(status["available_languages"])

def test_mixed_pdf_requires_ocr(documents):
    assert redactor.is_native_text_pdf(documents["native"])
    assert not redactor.is_native_text_pdf(documents["scan"])
    assert not redactor.is_native_text_pdf(documents["mixed"])

def test_native_permanent_removal_and_source_preserved(documents):
    src = documents["native"]; before = src.read_bytes()
    found = app.analyze_pdf(str(src))
    assert set(APPROVED) <= {r["text"] for r in found}
    result = app.redact_pdf(str(src), APPROVED)
    target = Path(result["output_path"])
    assert src.read_bytes() == before and target != src
    with fitz.open(target) as d:
        text = "\n".join(p.get_text() for p in d)
        assert all(value.casefold() not in text.casefold() for value in APPROVED)
        assert "KEEP THIS REFERENCE 987654" in text
        assert all(not list(p.annots() or []) for p in d)
        for xref in range(1, d.xref_length()):
            stream = d.xref_stream(xref) or b""
            assert b"123,45 EUR" not in stream
        d[0].get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(OUT/"native_after.png")
    with fitz.open(src) as d:
        d[0].get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(OUT/"native_before.png")

def test_unicode_casefold_and_no_substring_redaction():
    src = native(OUT/"synthetic_casefold.pdf", ["Kovács Ágnes", "KOVÁCS ÁGNES", "Anna", "Annabelle"])
    app.analyze_pdf(str(src)); out = app.redact_pdf(str(src), ["Kovács Ágnes", "Anna"])
    with fitz.open(out["output_path"]) as d:
        text = d[0].get_text()
        assert "KOVÁCS ÁGNES" not in text and "Kovács Ágnes" not in text
        assert "Annabelle" in text

def test_missing_approved_value_refuses_partial_export(documents):
    src = documents["native"]
    app.analyze_pdf(str(src))
    exports_before = set(OUT.glob("synthetic_native_redacted*.pdf"))
    with pytest.raises(ValueError, match="some approved values"):
        app.redact_pdf(str(src), ["Kovács Ágnes", "Nonexistent Synthetic Value"])
    assert set(OUT.glob("synthetic_native_redacted*.pdf")) == exports_before

def test_changed_source_requires_new_analysis():
    src = native(OUT/"synthetic_changed.pdf")
    app.analyze_pdf(str(src)); native(src, ["Changed synthetic source", "Kovács Ágnes"])
    with pytest.raises(ValueError, match="new or changed"):
        app.redact_pdf(str(src), ["Kovács Ágnes"])

def test_repeated_export_preserves_previous_output(documents):
    src = documents["native"]; app.analyze_pdf(str(src))
    first = app.redact_pdf(str(src), ["Kovács Ágnes"])
    content = Path(first["output_path"]).read_bytes()
    second = app.redact_pdf(str(src), ["Őri Zsófia"])
    assert first["output_path"] != second["output_path"]
    assert Path(first["output_path"]).read_bytes() == content

@pytest.mark.parametrize("kind", ["scan", "mixed"])
def test_actual_ocr_pixel_removal(kind, documents):
    src = documents[kind]; before = src.read_bytes()
    hits = app.analyze_pdf(str(src))
    # OCR is imperfect; assert the fixture actually produced the selected candidates.
    detected = {h["text"] for h in hits}
    assert set(APPROVED) <= detected, detected
    values = APPROVED
    with redactor.tempfile.TemporaryDirectory(prefix="redactor-fixture-") as folder:
        source_image, source_png = redactor._render_single_page(src, 1, Path(folder))
        try:
            data = redactor.pytesseract.image_to_data(source_image, lang=redactor.OCR_LANGUAGE, config=redactor.OCR_CONFIG, output_type=redactor.Output.DICT)
            original_boxes = redactor._find_ocr_redaction_boxes(data, redactor._build_ocr_targets(values))
            assert original_boxes
        finally:
            source_image.close()
    result = app.redact_pdf(str(src), values)
    assert src.read_bytes() == before and result["processing_mode"] == "ocr"
    with fitz.open(result["output_path"]) as d:
        assert not d[0].get_text().strip()
        assert len(d[0].get_images(full=True)) == 1
        image_data = d.extract_image(d[0].get_images(full=True)[0][0])["image"]
        with Image.open(io.BytesIO(image_data)) as image:
            text = redactor.pytesseract.image_to_string(image, lang=redactor.OCR_LANGUAGE, config=redactor.OCR_CONFIG)
            assert "Kovács" not in text and "Székesfehérvár" not in text
            assert "987654" in text
            # Check that exported image data itself contains solid-black redaction areas.
            for left, top, width, height in original_boxes:
                assert image.convert("RGB").crop((left, top, left + width, top + height)).getextrema() == ((0,0),(0,0),(0,0))
        assert not list(d[0].annots() or []) and d.embfile_count() == 0
        d[0].get_pixmap(matrix=fitz.Matrix(1.2,1.2)).save(OUT/(kind+"_after.png"))
    with fitz.open(src) as d:
        d[0].get_pixmap(matrix=fitz.Matrix(1.2,1.2)).save(OUT/(kind+"_before.png"))

def test_native_metadata_and_embedded_source_removed():
    src = native(OUT/"synthetic_metadata_base.pdf")
    with fitz.open(src) as d:
        d.set_metadata({"author":"Kovács Ágnes", "title":"Kovács Ágnes"})
        d.embfile_add("original.txt", b"Kovacs Agnes synthetic attachment")
        target = OUT/"synthetic_metadata.pdf"; d.save(target)
    app.analyze_pdf(str(target)); result = app.redact_pdf(str(target), ["Kovács Ágnes"])
    with fitz.open(result["output_path"]) as d:
        assert not d.metadata.get("author") and not d.metadata.get("title")
        assert d.embfile_count() == 0

def test_explicit_approval_required(documents):
    with pytest.raises(ValueError, match="Select at least one"):
        app.redact_pdf(str(documents["native"]), [])
