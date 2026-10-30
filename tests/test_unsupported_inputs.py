from pathlib import Path
import pymupdf as fitz
import pytest
from test_redactor import OUT, native, app

def test_encrypted_document_refuses_without_export():
    source = native(OUT/'synthetic_unencrypted.pdf')
    encrypted = OUT/'synthetic_encrypted.pdf'
    with fitz.open(source) as d:
        d.save(encrypted,encryption=fitz.PDF_ENCRYPT_AES_256,user_pw='synthetic-password',owner_pw='synthetic-owner')
    with pytest.raises(ValueError,match='Password-protected'):
        app.analyze_pdf(str(encrypted))

def test_interactive_form_requires_explicit_flattening_decision():
    source = OUT/'synthetic_form.pdf'
    with fitz.open() as d:
        p=d.new_page();p.insert_text((40,40),'Synthetic form')
        field=fitz.Widget();field.field_name='synthetic_name';field.field_type=fitz.PDF_WIDGET_TYPE_TEXT
        field.field_value='Kovács Ágnes';field.rect=fitz.Rect(40,80,240,110);p.add_widget(field)
        d.save(source)
    with pytest.raises(ValueError,match='Interactive PDF forms'):
        app.analyze_pdf(str(source))
