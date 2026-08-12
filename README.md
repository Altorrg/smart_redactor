# PDF Smart Redactor GUI

PDF Smart Redactor GUI is a local Eel desktop application for permanently redacting approved amounts, names, and city candidates from native and scanned PDF files.

## Installation

1. Install Python 3.10 or newer.
2. Put an approved Tesseract OCR distribution in `tools/tesseract`.
3. Put an approved Poppler distribution in `tools/poppler`.
4. Install the Python packages:

```powershell
python -m pip install -r requirements.txt
```

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
