# PDF Smart Redactor GUI

PDF Smart Redactor GUI is a local Eel desktop application for permanently redacting approved amounts, names, and city candidates from native and scanned PDF files.

## Installation

1. Install Python 3.10 or newer.
2. Put an approved Tesseract OCR distribution in `tools/tesseract`.
3. Put the official Hungarian and English OCR models in `tools/tessdata`.
4. Install the Python packages:

```powershell
python -m pip install -r requirements.txt
```

On Windows, `install_dependencies.bat` creates a project-local `.venv` using
the Python launcher and installs these requirements. `index.bat` prefers that
environment. No Poppler installation is needed: PyMuPDF renders the pages.

The reviewed test bundle includes the Apache-2.0 `hun` and `eng` models and
their license. For a source checkout, obtain those models from the official
`tesseract-ocr/tessdata_fast` repository. The application never downloads them
while processing a document. Installed PDF24 Tesseract is also detected.

## Start

Double-click `index.bat`. It checks the locally installed Python dependencies,
starts the loopback-only backend on an automatically selected free port, waits
until it is ready, and opens the exact local URL. The launcher never downloads
packages or makes external network requests. Missing packages must be installed
through an approved internal package source.

When browsing inside the `web` directory, use `START_BACKEND.bat` beside
`index.html`. It delegates to the root launcher and opens the working Eel URL.

Alternatively, start the backend directly:

```powershell
python src/app.py
```

Do not open `web/index.html` directly. Browser security prevents an HTML file
from starting a local Python process. The interface requires the local Eel
backend and intentionally disables PDF processing when that backend is unavailable.

No `PATH` modification is required. See `tools/README.md` for the supported
project-local directory structure.

All document processing is performed locally. The application makes no external API calls and uses no database.

## Reviewed behavior (2026-10-30)

- Hungarian accented names, company names, cities and amounts are candidates,
  not guaranteed complete or correctly classified detections. Review every page.
- Labelled fields, titles/initials, compound company names, signed amounts,
  one-decimal amounts and nonbreaking thousands separators are supported.
- After analysis, use **Add text the detector missed** for an exact value absent
  from the suggestions. The new entry remains unchecked until you approve it.
  Adding entries preserves your existing checkbox selections.
- Nothing is preselected. Only explicitly checked values are submitted.
- Matching preserves word boundaries, amount signs and decimal separators.
  Closely spaced line wraps and hyphenated line breaks are handled when their
  layout is unambiguous. Separate columns are not joined into one name.
- Analysis is bound to the source file's SHA256. Changed files require analysis again.
- If any approved value cannot be located, export stops instead of silently
  publishing a partially redacted document.
- Native export also checks the remaining extracted text before saving. A
  repeated value left behind by ambiguous layout stops publication. This check
  does not establish completeness for scans or incorrectly encoded PDF text.
- Existing exports and the source are never overwritten. Subsequent outputs use
  `_redacted_2.pdf`, `_redacted_3.pdf`, etc.
- Native redaction removes matching text and scrubs metadata/attachments and
  other hidden content. Interactive forms are refused; use a separately reviewed
  flattened copy. The original remains unchanged.
- PDF notes, free-text annotations and annotation attachments are explicitly
  removed from native exports. Clearing annotation replies alone does not remove
  the original comment, which may contain the approved sensitive value.
- Every PDF containing raster images uses the conservative OCR/raster path,
  including mixed native/image PDFs. The output loses searchable text and
  interactive features; page dimensions are preserved. Small logos also trigger
  this path. OCR errors, handwriting and unusual layouts still require manual review.
- OCR defaults to `hun+eng`. Configure `PDF_REDACTOR_OCR_LANG`,
  `PDF_REDACTOR_TESSERACT_PATH` and `PDF_REDACTOR_TESSDATA_PATH` if needed.

## Validation

Windows Python 3.12, Eel 0.18.2, PyMuPDF 1.28.2, Pillow 12.3.0,
pytesseract 0.3.13 and Tesseract 5.4.1 were exercised with synthetic PDFs.
The expanded suite passes 76 Python tests and 17 frontend assertions. It includes
16 explicit Hungarian name/company/address cases, 20 amount formats, a generated
three-page native corpus, a Hungarian invoice scan, wrapped/repeated values,
Unicode spaces, manual entries and rotation. Expectations are authored separately
from the detector. These results describe these fixtures, not general OCR accuracy.
The independent 2026-10-30 review adds two-page native/rotated and mixed
native/raster exports, manual reference removal, retention of unapproved values,
unchanged originals, and removal of sensitive content in PDF annotations.
See [the validation report](docs/VALIDATION_20261030.md) for scope and limits.
Run `python -m pip install -r requirements-dev.txt` then `python -m pytest tests`.
`node tests/frontend_test.cjs` additionally checks the actual frontend's explicit
selection logic with a mocked DOM; the Python suite separately starts the real
Windows BAT launcher and uses the real Eel HTTP/WebSocket bridge.

This is a tested repair, not a general anonymization, OCR-accuracy or compliance
guarantee. Always visually review the exported copy before sharing it.

