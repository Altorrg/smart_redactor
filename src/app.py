"""Eel application entry point for the local PDF Smart Redactor GUI."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import threading
import urllib.error
import urllib.request
import uuid
import webbrowser
from importlib.util import find_spec
from pathlib import Path
from typing import Any

try:
    import eel
except ModuleNotFoundError as error:
    if error.name == "eel":
        raise SystemExit(
            "Eel is not installed. Install requirements.txt from an approved internal package source."
        ) from None
    raise

from nlp_engine import SensitiveEntity, find_sensitive_entities


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIRECTORY = PROJECT_ROOT / "web"
MAX_PDF_SIZE_BYTES = 512 * 1024 * 1024
MAX_APPROVED_ENTITIES = 1_000
MAX_ENTITY_LENGTH = 256

LOGGER = logging.getLogger("pdf_smart_redactor")


class PathValidationError(ValueError):
    """Raised when a frontend-supplied path fails security validation."""


def _sanitize_pdf_path(filepath: Any) -> Path:
    """Validate and canonicalize a local PDF path from the frontend.

    Relative paths, parent traversal segments, URLs, UNC network paths, control
    characters, non-PDF files, symbolic links, and oversized files are rejected.
    The canonical path is returned only after the file has been verified.
    """

    if not isinstance(filepath, str):
        raise PathValidationError("The PDF path must be a string.")

    raw_path = filepath.strip()
    if not raw_path or len(raw_path) > 4_096:
        raise PathValidationError("The PDF path is empty or too long.")
    if any(ord(character) < 32 for character in raw_path):
        raise PathValidationError("The PDF path contains invalid control characters.")
    if "://" in raw_path or raw_path.startswith(("\\\\", "//")):
        raise PathValidationError("Only local filesystem paths are permitted.")

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        raise PathValidationError("An absolute local PDF path is required.")
    if ".." in candidate.parts:
        raise PathValidationError("Parent directory traversal is not permitted.")
    if candidate.is_symlink():
        raise PathValidationError("Symbolic links are not accepted as PDF inputs.")

    try:
        canonical_path = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise PathValidationError("The selected PDF does not exist or cannot be accessed.") from error

    if canonical_path.suffix.casefold() != ".pdf":
        raise PathValidationError("Only files with a .pdf extension are accepted.")
    if not canonical_path.is_file():
        raise PathValidationError("The selected path is not a regular file.")

    try:
        file_size = canonical_path.stat().st_size
    except OSError as error:
        raise PathValidationError("The selected PDF cannot be inspected.") from error

    if file_size < 1:
        raise PathValidationError("The selected PDF is empty.")
    if file_size > MAX_PDF_SIZE_BYTES:
        raise PathValidationError("The selected PDF exceeds the 512 MB safety limit.")

    return canonical_path


def _sanitize_approved_entities(approved_entities_list: Any) -> list[str]:
    """Validate entity strings received from JavaScript before PDF processing."""

    if not isinstance(approved_entities_list, list):
        raise ValueError("Approved entities must be provided as a list.")
    if not approved_entities_list:
        raise ValueError("Select at least one entity to redact.")
    if len(approved_entities_list) > MAX_APPROVED_ENTITIES:
        raise ValueError(
            f"No more than {MAX_APPROVED_ENTITIES} entities may be processed at once."
        )

    sanitized: list[str] = []
    seen: set[str] = set()
    for entity in approved_entities_list:
        if not isinstance(entity, str):
            raise ValueError("Every approved entity must be a string.")
        cleaned = " ".join(entity.split()).strip()
        if not cleaned or len(cleaned) > MAX_ENTITY_LENGTH:
            raise ValueError("An approved entity is empty or too long.")
        if any(ord(character) < 32 for character in cleaned):
            raise ValueError("An approved entity contains invalid control characters.")

        normalized = cleaned.casefold()
        if normalized not in seen:
            seen.add(normalized)
            sanitized.append(cleaned)

    return sanitized


def _temporary_output_path(output_path: Path) -> Path:
    """Create a collision-resistant path for an atomic output operation."""

    token = uuid.uuid4().hex
    return output_path.parent / f".{output_path.stem}.{token}.temporary.pdf"


def _load_redactor() -> Any:
    """Load PDF dependencies lazily so the UI can report missing packages."""

    try:
        import redactor
    except ModuleNotFoundError as error:
        missing_name = error.name or "unknown package"
        raise RuntimeError(
            f"Missing Python package: {missing_name}. Install requirements.txt first."
        ) from None
    return redactor


@eel.expose
def get_runtime_status() -> dict[str, object]:
    """Return local dependency availability without making network requests."""

    package_modules = {
        "PyMuPDF": "fitz",
        "pytesseract": "pytesseract",
        "pdf2image": "pdf2image",
        "Pillow": "PIL",
    }
    missing_python_packages = [
        package_name
        for package_name, module_name in package_modules.items()
        if find_spec(module_name) is None
    ]

    ocr_runtime: dict[str, object] = {
        "ready": False,
        "missing_tools": [],
        "tesseract_path": "",
        "poppler_path": "",
    }
    if not missing_python_packages:
        ocr_runtime = _load_redactor().configure_ocr_runtime()

    missing_ocr_tools = list(ocr_runtime["missing_tools"])

    return {
        "python_ready": not missing_python_packages,
        "ocr_ready": not missing_python_packages and ocr_runtime["ready"] is True,
        "missing_python_packages": missing_python_packages,
        "missing_ocr_tools": missing_ocr_tools,
        "tesseract_path": ocr_runtime["tesseract_path"],
        "poppler_path": ocr_runtime["poppler_path"],
    }


@eel.expose
def select_pdf() -> str:
    """Open a native local PDF picker and return a validated absolute path."""

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected_path = filedialog.askopenfilename(
                parent=root,
                title="Select a PDF",
                filetypes=(("PDF files", "*.pdf"),),
            )
        finally:
            root.destroy()

        if not selected_path:
            return ""
        return str(_sanitize_pdf_path(selected_path))
    except PathValidationError as error:
        raise ValueError(str(error)) from None
    except Exception as error:
        LOGGER.exception("Local file selection failed: %s", type(error).__name__)
        raise RuntimeError("The local PDF picker could not be opened.") from None


@eel.expose
def analyze_pdf(filepath: str) -> list[SensitiveEntity]:
    """Analyze a local PDF and return regex-detected sensitive entities.

    Native text is extracted directly. PDFs containing scanned pages are OCRed
    locally with Tesseract using bounded, page-at-a-time image processing.
    """

    try:
        pdf_path = _sanitize_pdf_path(filepath)
        redactor = _load_redactor()
        extracted_text, extraction_mode = redactor.extract_text_for_analysis(pdf_path)
        LOGGER.info("PDF analysis completed using %s extraction.", extraction_mode)
        return find_sensitive_entities(extracted_text)
    except (PathValidationError, ValueError) as error:
        raise ValueError(str(error)) from None
    except Exception as error:
        LOGGER.exception("Local PDF analysis failed: %s", type(error).__name__)
        raise RuntimeError(
            "PDF analysis failed. Verify that the PDF, Tesseract, and Poppler are available."
        ) from None


@eel.expose
def redact_pdf(filepath: str, approved_entities_list: list[str]) -> dict[str, object]:
    """Permanently redact approved entities and atomically save the output PDF."""

    temporary_path: Path | None = None
    try:
        pdf_path = _sanitize_pdf_path(filepath)
        approved_entities = _sanitize_approved_entities(approved_entities_list)
        output_path = pdf_path.with_name(f"{pdf_path.stem}_redacted.pdf")
        temporary_path = _temporary_output_path(output_path)
        redactor = _load_redactor()

        if redactor.is_native_text_pdf(pdf_path):
            redaction_count = redactor.redact_native_pdf(
                pdf_path,
                temporary_path,
                approved_entities,
            )
            processing_mode = "native"
        else:
            redaction_count = redactor.redact_scanned_pdf(
                pdf_path,
                temporary_path,
                approved_entities,
            )
            processing_mode = "ocr"

        if redaction_count < 1:
            raise ValueError("None of the approved entities could be located in the PDF.")

        os.replace(temporary_path, output_path)
        temporary_path = None
        LOGGER.info("Redacted PDF saved using %s processing.", processing_mode)

        return {
            "success": True,
            "output_path": str(output_path),
            "processing_mode": processing_mode,
            "redaction_count": redaction_count,
        }
    except (PathValidationError, ValueError) as error:
        raise ValueError(str(error)) from None
    except Exception as error:
        LOGGER.exception("Local PDF redaction failed: %s", type(error).__name__)
        raise RuntimeError(
            "PDF redaction failed. Verify write access and local OCR dependencies."
        ) from None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _parse_arguments() -> argparse.Namespace:
    """Parse optional launch settings used for local testing and packaging."""

    parser = argparse.ArgumentParser(description="Start PDF Smart Redactor GUI.")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the local Eel server without opening a browser window.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Loopback port to use. Zero selects an available port automatically.",
    )
    return parser.parse_args()


def _find_available_loopback_port() -> int:
    """Reserve and return an available TCP port on the loopback interface."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
        probe_socket.bind(("127.0.0.1", 0))
        return int(probe_socket.getsockname()[1])


def _open_interface_when_ready(interface_url: str) -> None:
    """Wait for the local server and open its exact URL in the default browser."""

    for _ in range(80):
        try:
            with urllib.request.urlopen(interface_url, timeout=0.5):
                webbrowser.open(interface_url, new=1)
                return
        except (OSError, urllib.error.URLError):
            threading.Event().wait(0.25)
    LOGGER.error("The local interface did not become ready: %s", interface_url)


def main() -> None:
    """Initialize Eel and launch the loopback-only desktop interface."""

    arguments = _parse_arguments()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    eel.init(
        str(WEB_DIRECTORY),
        allowed_extensions=[".html", ".css", ".js"],
    )
    selected_port = arguments.port or _find_available_loopback_port()
    interface_url = f"http://127.0.0.1:{selected_port}/index.html"
    start_options = {
        "host": "127.0.0.1",
        "port": selected_port,
        "size": (980, 780),
        "block": True,
    }
    print(f"PDF Smart Redactor is running at {interface_url}")

    if arguments.no_browser:
        eel.start("index.html", mode=False, **start_options)
        return

    browser_thread = threading.Thread(
        target=_open_interface_when_ready,
        args=(interface_url,),
        daemon=True,
    )
    browser_thread.start()
    eel.start("index.html", mode=False, **start_options)


if __name__ == "__main__":
    main()
