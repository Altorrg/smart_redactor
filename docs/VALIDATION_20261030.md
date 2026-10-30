# Independent functional review - 2026-10-30

The existing repair was independently exercised on Windows with synthetic data.
No customer PDF, personal document or private project was used or published.

## Results

| Check | Result |
|---|---|
| Existing Python suite | 74 passed before the independent checks |
| New independent regression checks | 2 passed after the annotation fix |
| Final combined Python suite | 76 passed |
| Frontend selection/state assertions | 17 passed; mocked DOM and backend |
| Windows BAT launcher, Eel HTTP and WebSocket processing | Passed with the real local backend |
| Native/rotated two-page export | Approved values absent; nearby unapproved amount retained |
| Mixed native/raster two-page export | Real Hungarian/English OCR; redacted images re-read with OCR |
| Manual reference removal | Reference removed on both mixed pages; public control value retained |
| Original file preservation | Input bytes unchanged |
| Hidden content | Metadata, outline, document attachments and annotations removed in the native fixture |
| Visual review | All four new exported pages rendered and inspected |

## Defect reproduced and fixed

The original repair called `Document.scrub()`, but its annotation-reply cleanup
does not remove an original text note. An approved name disappeared from visible
page text while surviving in the note's `content` field. The new native test
reproduced this failure before the fix. Native export now explicitly deletes
remaining annotations, including notes, free-text and file annotations, before
scrubbing and saving. The test also confirms document metadata and embedded
source attachments are removed.

## Tested environment

- Windows, Python 3.12
- Eel 0.18.2, PyMuPDF 1.28.2, Pillow 12.3.0, pytesseract 0.3.13
- Local Tesseract 5.4.1 with `hun+eng` models
- Pytest for the Python checks; Node.js for the frontend assertions

Three Eel/pyparsing deprecation warnings remain; they did not fail the checks.

## Limits and use

This is a functional regression review, not a complete security audit or an
anonymization/compliance guarantee. The detector uses regular expressions and
OCR; neither guarantees discovery of every sensitive value. Review suggestions,
add missed exact values manually, approve the intended selections, then inspect
every exported page before sharing it. Scanned and mixed documents are flattened
to raster pages and lose searchable text. Forms and password-protected files are
refused. Annotation removal also intentionally discards non-sensitive comments.

Reproduce from a Windows checkout with local OCR installed:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
node tests/frontend_test.cjs
```

The repository contains source and synthetic test generators, not an EXE or a
bundled OCR engine. OCR language files and environment setup are described in
the root README and `tools/README.md`.
