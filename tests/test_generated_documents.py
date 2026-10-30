"""Generated Hungarian examples with independent expected values and real PDF exports."""
from __future__ import annotations

import io
import json
from pathlib import Path

import fitz
import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas

from test_redactor import FONT, OUT, app, native, redactor
from nlp_engine import find_sensitive_entities

# Expectations are written explicitly; they are not derived from the detector.
NAME_CASES = [
    ("Név Kovács Ágnes", "Kovács Ágnes"),
    ("Név: Őri Zsófia", "Őri Zsófia"),
    ("Ügyfél = Tóth-Szabó Éva", "Tóth-Szabó Éva"),
    ("Kapcsolattartó: dr. Kiss Júlia", "dr. Kiss Júlia"),
    ("Megrendelő – K. Ágnes", "K. Ágnes"),
    ("Dr. Nagy Béla", "Dr. Nagy Béla"),
    ("Prof. Varga Tamás", "Prof. Varga Tamás"),
    ("ifj. Farkas Áron", "ifj. Farkas Áron"),
    ("Cégnév: Minta-2026 és Társa Kft.", "Minta-2026 és Társa Kft."),
    ("Minta-2026 és Társa Kft.", "Minta-2026 és Társa Kft."),
    ("Árvíztűrő Építő Zrt.", "Árvíztűrő Építő Zrt."),
    ("Szállító: Duna & Tisza Bt.", "Duna & Tisza Bt."),
    ("Város: Hódmezővásárhely", "Hódmezővásárhely"),
    ("Település Balatonalmádi", "Balatonalmádi"),
    ("Székhely: 1111 Budapest, Minta utca 42.", "1111 Budapest, Minta utca 42."),
    ("Ügyfél: O’Connor Anna", "O’Connor Anna"),
]
AMOUNT_CASES = [
    "-1 234,56 Ft", "+1 234,56 Ft", "−1 234,56 Ft", "12,5 €", "€ 12,50",
    "1234 Ft", "1.234,56 EUR", "1,234.56 USD", "$1,234.56", "£ 99.50",
    "HUF 1 250 000", "CHF -123,45", "1\u00a0234,56 Ft", "1\u202f234,56 Ft",
    "12,- Ft", "0,00 EUR", "JPY 1000", "1000 CAD", "AUD 12.50", "42 forint",
]

@pytest.mark.parametrize("text, expected", NAME_CASES)
def test_generated_name_fields(text, expected):
    values = [e["text"] for e in find_sensitive_entities(text)]
    assert values == [expected], values


@pytest.mark.parametrize("value", AMOUNT_CASES)
def test_generated_amount_formats(value):
    values = [e["text"] for e in find_sensitive_entities("Összeg: " + value) if e["category"] == "amount"]
    assert values == [" ".join(value.split())], values


@pytest.mark.parametrize("text", ["2026.10.28", "A2-987654", "12,3456 EUR", "EUR 12,3456", "1234\nFt"])
def test_generated_non_amounts_are_not_partial_amounts(text):
    assert not [e for e in find_sensitive_entities(text) if e["category"] == "amount"]


def test_word_boundaries_signs_and_decimal_values_survive_native_export():
    source = native(OUT/"synthetic_generated_boundaries.pdf", [
        "Anna Maria", "AnnaMaria", "-1 234,56 Ft", "1 234,56 Ft",
        "123,45 EUR", "12,345 EUR", "KEEP 987654",
    ])
    before = source.read_bytes()
    app.analyze_pdf(str(source))
    result = app.redact_pdf(str(source), ["Anna Maria", "-1 234,56 Ft", "123,45 EUR"])
    with fitz.open(result["output_path"]) as document:
        text = document[0].get_text()
        assert "Anna Maria" not in text and "-1 234,56 Ft" not in text and "123,45 EUR" not in text
        for value in ["AnnaMaria", "1 234,56 Ft", "12,345 EUR", "987654"]:
            assert value in text, text
    assert source.read_bytes() == before


def test_repeated_wrapped_and_hyphenated_values_on_multiple_pages():
    source = OUT/"synthetic_generated_wrapped.pdf"
    pdf = canvas.Canvas(str(source), pagesize=(595, 842))
    pdf.setFont("FixtureArial", 16)
    block = pdf.beginText(45, 790); block.setLeading(21)
    for line in ["Kovács Ágnes", "Kovács", "Ágnes", "Hódmező-", "vásárhely", "KEEP 987654"]:
        block.textLine(line)
    pdf.drawText(block); pdf.showPage(); pdf.setFont("FixtureArial", 16)
    pdf.drawString(45, 790, "KOVÁCS ÁGNES"); pdf.drawString(45, 750, "SECOND PAGE KEEP")
    pdf.save()
    before = source.read_bytes(); app.analyze_pdf(str(source))
    result = app.redact_pdf(str(source), ["Kovács Ágnes", "Hódmezővásárhely"])
    with fitz.open(result["output_path"]) as document:
        text = "\n".join(p.get_text() for p in document)
        for fragment in ["Kovács", "Ágnes", "KOVÁCS", "ÁGNES", "Hódmező", "vásárhely"]:
            assert fragment not in text, text
        assert len(document) == 2 and "987654" in text and "SECOND PAGE KEEP" in text
        for n, page in enumerate(document):
            page.get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(OUT/f"generated_wrapped_after_{n+1}.png")
    assert source.read_bytes() == before


def test_separate_columns_do_not_form_a_name():
    source = OUT/"synthetic_generated_columns.pdf"
    pdf = canvas.Canvas(str(source), pagesize=(595,842)); pdf.setFont("FixtureArial",16)
    pdf.drawString(45,790,"Kovács"); pdf.drawString(390,790,"Ágnes"); pdf.save()
    app.analyze_pdf(str(source))
    with pytest.raises(ValueError, match="some approved values"):
        app.redact_pdf(str(source), ["Kovács Ágnes"])


def test_one_match_does_not_hide_an_unremoved_repeated_value():
    source = native(OUT/"synthetic_generated_ambiguous_repeat.pdf", ["Kovács Ágnes","Kovács","Ágnes","KEEP 987654"])
    before = source.read_bytes(); app.analyze_pdf(str(source))
    previous = set(OUT.glob("synthetic_generated_ambiguous_repeat_redacted*.pdf"))
    with pytest.raises(ValueError, match="approved text remains"):
        app.redact_pdf(str(source),["Kovács Ágnes"])
    assert source.read_bytes() == before
    assert previous == set(OUT.glob("synthetic_generated_ambiguous_repeat_redacted*.pdf"))


def test_all_generated_values_in_native_pdf():
    source = OUT/"synthetic_generated_corpus.pdf"
    rows = [(text, expected) for text, expected in NAME_CASES]
    rows += [("Összeg: " + value, " ".join(value.split())) for value in AMOUNT_CASES]
    pdf = canvas.Canvas(str(source), pagesize=(595,842))
    for page_number, start in enumerate(range(0,len(rows),16),1):
        pdf.setFont("FixtureArial",14)
        pdf.drawString(45,800,f"GENERATED CORPUS - PAGE {page_number}")
        for line, (text, _) in enumerate(rows[start:start+16]): pdf.drawString(45,750-line*38,text)
        pdf.drawString(45,55,"KEEP 987654"); pdf.showPage()
    pdf.save()
    before = source.read_bytes()
    detected = {e["text"] for e in app.analyze_pdf(str(source))}
    expected = {value for _,value in rows}
    assert expected <= detected, expected-detected
    result = app.redact_pdf(str(source),sorted(expected))
    with fitz.open(result["output_path"]) as document:
        for number, page in enumerate(document,1):
            text = page.get_text()
            remaining = [" ".join(row.split()).replace(value, "").strip() for row,value in rows[(number-1)*16:number*16]]
            assert [line.strip() for line in text.splitlines() if line.strip()] == [f"GENERATED CORPUS - PAGE {number}",*[v for v in remaining if v],"KEEP 987654"], text
            page.get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(OUT/f"generated_corpus_after_{number}.png")
    assert source.read_bytes() == before


def test_company_ampersand_is_not_ignored():
    source = native(OUT/"synthetic_generated_ampersand.pdf",["Duna & Tisza Bt.","Duna Tisza Bt."])
    app.analyze_pdf(str(source)); result = app.redact_pdf(str(source),["Duna & Tisza Bt."])
    with fitz.open(result["output_path"]) as document:
        assert document[0].get_text().strip() == "Duna Tisza Bt."


def test_manual_text_not_suggested_by_detector_can_be_redacted():
    source = native(OUT/"synthetic_generated_manual.pdf",["kimaradt személy","KEEP 987654"])
    detected = app.analyze_pdf(str(source))
    assert "kimaradt személy" not in {e["text"] for e in detected}
    result = app.redact_pdf(str(source),["kimaradt személy"])
    with fitz.open(result["output_path"]) as document:
        assert document[0].get_text().strip() == "KEEP 987654"


def test_rotated_native_page_keeps_display_dimensions():
    base = native(OUT/"synthetic_generated_rotation_base.pdf", ["Kovács Ágnes","KEEP 987654"])
    source = OUT/"synthetic_generated_rotated.pdf"
    with fitz.open(base) as document:
        document[0].set_rotation(90); document.save(source)
    app.analyze_pdf(str(source)); result = app.redact_pdf(str(source),["Kovács Ágnes"])
    with fitz.open(result["output_path"]) as document:
        assert document[0].rect.width == 842 and document[0].rect.height == 595
        assert document[0].get_text().strip() == "KEEP 987654"


def test_ocr_word_layout_and_word_boundaries():
    # Layout-only edge cases complement the real OCR integration tests below.
    words = ["Anna", "Maria", "AnnaMaria", "Kovács", "Ágnes", "Hódmező-", "vásárhely"]
    lines = [1,1,2,3,4,5,6]
    xs = [40,100,40,40,40,40,40]; ys = [20,20,50,80,105,130,155]
    data = {"text":words, "conf":[95]*7, "left":xs, "top":ys, "width":[50]*7, "height":[20]*7,
        "block_num":[1]*7, "par_num":[1]*7, "line_num":lines}
    found = set()
    boxes = redactor._find_ocr_redaction_boxes(data, redactor._build_ocr_targets(["Anna Maria", "Kovács Ágnes", "Hódmezővásárhely"]), found)
    assert len(boxes) == 6 and (40,50,50,20) not in boxes
    assert found == {"anna maria", "kovács ágnes", "hódmezővásárhely"}


def test_actual_generated_hungarian_invoice_scan():
    source = OUT/"synthetic_generated_invoice.pdf"
    rows = ["SYNTHETIC TEST DOCUMENT", "Név: Tóth-Szabó Éva", "Cég: Minta-2026 és Társa Kft.",
        "Város: Hódmezővásárhely", "Összeg: -1 234,56 Ft", "KEEP REFERENCE 987654"]
    approved = ["Tóth-Szabó Éva", "Minta-2026 és Társa Kft.", "Hódmezővásárhely", "-1 234,56 Ft"]
    image = Image.new("RGB", (1800,2400), "white"); draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), 44)
    for n, row in enumerate(rows): draw.text((100,100+n*130),row,font=font,fill="black")
    png = io.BytesIO(); image.save(png,"PNG"); image.close()
    with fitz.open() as document:
        page = document.new_page(width=595,height=842); page.insert_image(page.rect,stream=png.getvalue()); document.save(source)
    before = source.read_bytes(); detected = {e["text"] for e in app.analyze_pdf(str(source))}
    assert set(approved) <= detected, detected
    result = app.redact_pdf(str(source), approved)
    with fitz.open(result["output_path"]) as document:
        assert len(document[0].get_images(full=True)) == 1 and not document[0].get_text().strip()
        data = document.extract_image(document[0].get_images(full=True)[0][0])["image"]
        with Image.open(io.BytesIO(data)) as exported:
            text = redactor.pytesseract.image_to_string(exported,lang=redactor.OCR_LANGUAGE,config=redactor.OCR_CONFIG)
            for value in ["Tóth", "Minta-2026", "Hódmezővásárhely", "234,56"]: assert value not in text, text
            assert "987654" in text, text
        document[0].get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(OUT/"generated_invoice_after.png")
    with fitz.open(source) as document:
        document[0].get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(OUT/"generated_invoice_before.png")
    assert source.read_bytes() == before
    (OUT/"generated-invoice-result.json").write_text(json.dumps({"expected":approved,"detected":sorted(detected),"export_ocr":text,"source_unchanged":True},ensure_ascii=False,indent=2),encoding="utf-8")
