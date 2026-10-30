"""Independent release checks with new synthetic data, not customer documents."""
from __future__ import annotations

import hashlib
import io
import fitz
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas

from test_redactor import FONT, OUT, app, redactor


def test_independent_native_pages_rotation_and_hidden_content():
    source = OUT / "independent_native_review.pdf"
    base = OUT / "independent_native_base.pdf"
    pdf = canvas.Canvas(str(base), pagesize=(595, 842))
    for name, amount, keep in [
        ("Fekete Réka", "9 876,54 EUR", "KEEP ALPHA 735921"),
        ("FEKETE RÉKA", "9 876,54 EUR", "KEEP BETA 268413"),
    ]:
        pdf.setFont("FixtureArial", 18)
        for n, line in enumerate(["INDEPENDENT SYNTHETIC REVIEW", name, amount, "9 876,55 EUR", keep]):
            pdf.drawString(45, 780 - n * 60, line)
        pdf.showPage()
    pdf.save()
    with fitz.open(base) as document:
        document[1].set_rotation(90)
        document.set_metadata({"author": "Fekete Réka", "subject": "9 876,54 EUR"})
        document.embfile_add("synthetic-private.txt", b"SYNTHETIC hidden payload")
        document.set_toc([[1, "Fekete Réka", 1]])
        document[0].add_text_annot((400, 700), "Fekete Réka")
        document[0].add_freetext_annot(fitz.Rect(350, 600, 550, 640), "Fekete Reka")
        document[0].add_file_annot((400, 650), b"Fekete Reka", "synthetic-note.txt")
        document.save(source)
        dimensions = [(p.rect.width, p.rect.height) for p in document]
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    app.analyze_pdf(str(source))
    result = app.redact_pdf(str(source), ["Fekete Réka", "9 876,54 EUR"])
    assert result["processing_mode"] == "native"
    with fitz.open(result["output_path"]) as document:
        assert len(document) == 2 and not document.get_toc()
        assert document.embfile_count() == 0 and not document.metadata.get("author")
        assert [(p.rect.width, p.rect.height) for p in document] == dimensions
        for n, page in enumerate(document):
            text = page.get_text()
            assert "fekete" not in text.casefold() and "9 876,54" not in text
            assert "9 876,55 EUR" in text
            assert ("735921" if n == 0 else "268413") in text
            assert not list(page.annots() or [])
            page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25)).save(OUT / f"independent_native_after_{n+1}.png")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_independent_multipage_mixed_export_and_manual_reference():
    """Real OCR on both a native-text page and a separate raster page."""
    native = OUT / "independent_mixed_base.pdf"
    source = OUT / "independent_mixed_review.pdf"
    approved = ["Fekete Réka", "6 543,21 EUR", "ZXQ-735921"]
    rows = ["INDEPENDENT SYNTHETIC REVIEW", "Név: Fekete Réka", "Összeg: 6 543,21 EUR", "ZXQ-735921", "KEEP PUBLIC 268413"]
    pdf = canvas.Canvas(str(native), pagesize=(595, 842))
    pdf.setFont("FixtureArial", 18)
    for n, line in enumerate(rows):
        pdf.drawString(45, 780 - n * 65, line)
    pdf.save()
    image = Image.new("RGB", (1800, 2400), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), 48)
    for n, line in enumerate(rows):
        draw.text((100, 100 + n * 170), line, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    image.close()
    with fitz.open(native) as document:
        page = document.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=buffer.getvalue())
        document.save(source)
    before = source.read_bytes()
    candidates = {entry["text"] for entry in app.analyze_pdf(str(source))}
    assert approved[0] in candidates and approved[1] in candidates
    # The reference is deliberately supplied manually, independently of detection.
    result = app.redact_pdf(str(source), approved)
    assert result["processing_mode"] == "ocr"
    with fitz.open(result["output_path"]) as document:
        assert len(document) == 2 and not document.embfile_count()
        for n, page in enumerate(document):
            assert not page.get_text().strip() and not list(page.annots() or [])
            assert (page.rect.width, page.rect.height) == (595, 842)
            images = page.get_images(full=True)
            assert len(images) == 1
            data = document.extract_image(images[0][0])["image"]
            with Image.open(io.BytesIO(data)) as exported:
                text = redactor.pytesseract.image_to_string(exported, lang=redactor.OCR_LANGUAGE, config=redactor.OCR_CONFIG)
                assert "Fekete" not in text and "543,21" not in text and "735921" not in text, text
                assert "268413" in text, text
            page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25)).save(OUT / f"independent_mixed_after_{n+1}.png")
    assert source.read_bytes() == before
