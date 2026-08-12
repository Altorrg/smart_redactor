"""Native-text and OCR-based physical PDF redaction functions."""

from __future__ import annotations

import gc
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Literal, Sequence

import fitz
import pytesseract
from pdf2image import convert_from_path, pdfinfo_from_path
from PIL import Image, ImageDraw
from pytesseract import Output


OCR_DPI = 300
MAX_RENDER_DIMENSION = 3000
MAX_OCR_PAGES = 500
MAX_EXTRACTED_TEXT_CHARACTERS = 20_000_000
PDFINFO_TIMEOUT_SECONDS = 30
PAGE_RENDER_TIMEOUT_SECONDS = 120
OCR_TIMEOUT_SECONDS = 120
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_TESSERACT_PATH: Path | None = None
LOCAL_POPPLER_PATH: Path | None = None
Image.MAX_IMAGE_PIXELS = 60_000_000


def _candidate_paths(environment_name: str, defaults: Sequence[Path]) -> list[Path]:
    """Build ordered executable or directory candidates without changing PATH."""

    candidates: list[Path] = []
    configured_value = os.environ.get(environment_name, "").strip()
    if configured_value:
        candidates.append(Path(configured_value).expanduser())
    candidates.extend(defaults)
    return candidates


def configure_ocr_runtime() -> dict[str, object]:
    """Locate project-local OCR tools and configure their absolute paths."""

    global LOCAL_TESSERACT_PATH, LOCAL_POPPLER_PATH

    tesseract_defaults = [
        PROJECT_ROOT / "tools" / "tesseract" / "tesseract.exe",
    ]
    for environment_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base_directory = os.environ.get(environment_name, "").strip()
        if not base_directory:
            continue
        if environment_name == "LOCALAPPDATA":
            tesseract_defaults.append(
                Path(base_directory) / "Programs" / "Tesseract-OCR" / "tesseract.exe"
            )
        else:
            tesseract_defaults.append(
                Path(base_directory) / "Tesseract-OCR" / "tesseract.exe"
            )

    LOCAL_TESSERACT_PATH = next(
        (
            candidate.resolve()
            for candidate in _candidate_paths(
                "PDF_REDACTOR_TESSERACT_PATH",
                tesseract_defaults,
            )
            if candidate.is_file()
        ),
        None,
    )
    tesseract_command = shutil.which("tesseract")
    if LOCAL_TESSERACT_PATH is not None:
        pytesseract.pytesseract.tesseract_cmd = str(LOCAL_TESSERACT_PATH)

    poppler_defaults = [
        PROJECT_ROOT / "tools" / "poppler" / "Library" / "bin",
        PROJECT_ROOT / "tools" / "poppler" / "bin",
    ]
    LOCAL_POPPLER_PATH = next(
        (
            candidate.resolve()
            for candidate in _candidate_paths(
                "PDF_REDACTOR_POPPLER_PATH",
                poppler_defaults,
            )
            if candidate.is_dir()
            and (candidate / "pdfinfo.exe").is_file()
            and (candidate / "pdftoppm.exe").is_file()
        ),
        None,
    )
    poppler_on_path = bool(shutil.which("pdfinfo") and shutil.which("pdftoppm"))

    missing_tools: list[str] = []
    if LOCAL_TESSERACT_PATH is None and not tesseract_command:
        missing_tools.append("tools/tesseract/tesseract.exe")
    if LOCAL_POPPLER_PATH is None and not poppler_on_path:
        missing_tools.append("tools/poppler")

    return {
        "ready": not missing_tools,
        "missing_tools": missing_tools,
        "tesseract_path": str(LOCAL_TESSERACT_PATH or tesseract_command or ""),
        "poppler_path": str(LOCAL_POPPLER_PATH or ("PATH" if poppler_on_path else "")),
    }


def _poppler_path_argument() -> str | None:
    """Return the explicit local Poppler directory when configured."""

    return str(LOCAL_POPPLER_PATH) if LOCAL_POPPLER_PATH is not None else None


configure_ocr_runtime()


def _prepare_entities(approved_entities: Sequence[str]) -> tuple[str, ...]:
    """Normalize and deduplicate approved entity values."""

    unique: dict[str, str] = {}
    for entity in approved_entities:
        cleaned = " ".join(entity.split()).strip()
        if cleaned:
            unique.setdefault(cleaned.casefold(), cleaned)
    return tuple(sorted(unique.values(), key=len, reverse=True))


def _get_page_count(pdf_path: Path) -> int:
    """Return a bounded page count using the Poppler metadata utility."""

    information = pdfinfo_from_path(
        str(pdf_path),
        poppler_path=_poppler_path_argument(),
        timeout=PDFINFO_TIMEOUT_SECONDS,
    )
    page_count = int(information.get("Pages", 0))
    if page_count < 1:
        raise ValueError("The PDF does not contain any pages.")
    if page_count > MAX_OCR_PAGES:
        raise ValueError(
            f"OCR is limited to {MAX_OCR_PAGES} pages per document to protect local resources."
        )
    return page_count


def _get_page_dimensions(pdf_path: Path) -> tuple[tuple[float, float], ...]:
    """Return each page's displayed width and height in PDF points."""

    with fitz.open(pdf_path) as document:
        return tuple((page.rect.width, page.rect.height) for page in document)


def is_native_text_pdf(pdf_path: Path) -> bool:
    """Return true when every content-bearing page has extractable text."""

    found_text = False
    with fitz.open(pdf_path) as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")
        if document.page_count < 1:
            raise ValueError("The PDF does not contain any pages.")

        for page in document:
            text = page.get_text("text").strip()
            if text:
                found_text = True
                continue
            if page.get_images(full=True):
                return False

    return found_text


def _render_single_page(
    pdf_path: Path,
    page_number: int,
    output_directory: Path,
) -> tuple[Image.Image, Path]:
    """Render one bounded-size PDF page and return its loaded Pillow image."""

    rendered_paths = convert_from_path(
        str(pdf_path),
        dpi=OCR_DPI,
        first_page=page_number,
        last_page=page_number,
        fmt="png",
        output_folder=str(output_directory),
        paths_only=True,
        thread_count=1,
        size=MAX_RENDER_DIMENSION,
        poppler_path=_poppler_path_argument(),
        timeout=PAGE_RENDER_TIMEOUT_SECONDS,
    )
    if len(rendered_paths) != 1:
        raise RuntimeError(f"Unable to render PDF page {page_number}.")

    rendered_path = Path(rendered_paths[0]).resolve()
    source_image = Image.open(rendered_path)
    source_image.load()

    if source_image.mode == "RGB":
        return source_image, rendered_path

    rgb_image = source_image.convert("RGB")
    source_image.close()
    return rgb_image, rendered_path


def _extract_native_text(pdf_path: Path) -> str:
    """Extract text from a native PDF with a bounded aggregate size."""

    page_text: list[str] = []
    character_count = 0
    with fitz.open(pdf_path) as document:
        for page in document:
            extracted = page.get_text("text")
            character_count += len(extracted)
            if character_count > MAX_EXTRACTED_TEXT_CHARACTERS:
                raise ValueError("Extracted text exceeds the local processing limit.")
            page_text.append(extracted)
    return "\n".join(page_text)


def _extract_ocr_text(pdf_path: Path) -> str:
    """OCR a scanned PDF one page at a time with explicit resource cleanup."""

    page_count = _get_page_count(pdf_path)
    extracted_pages: list[str] = []
    character_count = 0

    with tempfile.TemporaryDirectory(prefix="pdf-smart-redactor-ocr-") as temporary_name:
        temporary_directory = Path(temporary_name)

        for page_number in range(1, page_count + 1):
            image: Image.Image | None = None
            rendered_path: Path | None = None
            try:
                image, rendered_path = _render_single_page(
                    pdf_path,
                    page_number,
                    temporary_directory,
                )
                extracted = pytesseract.image_to_string(
                    image,
                    timeout=OCR_TIMEOUT_SECONDS,
                )
                character_count += len(extracted)
                if character_count > MAX_EXTRACTED_TEXT_CHARACTERS:
                    raise ValueError("OCR text exceeds the local processing limit.")
                extracted_pages.append(extracted)
            finally:
                if image is not None:
                    image.close()
                if rendered_path is not None:
                    rendered_path.unlink(missing_ok=True)
                del image
                gc.collect()

    return "\n".join(extracted_pages)


def extract_text_for_analysis(pdf_path: Path) -> tuple[str, Literal["native", "ocr"]]:
    """Extract PDF text locally, using OCR only when native text is unavailable."""

    if is_native_text_pdf(pdf_path):
        return _extract_native_text(pdf_path), "native"
    return _extract_ocr_text(pdf_path), "ocr"


def redact_native_pdf(
    input_path: Path,
    output_path: Path,
    approved_entities: Sequence[str],
) -> int:
    """Physically redact approved text from a native PDF using PyMuPDF.

    Args:
        input_path: Canonical path of the source PDF.
        output_path: Destination path for the redacted PDF.
        approved_entities: Exact entity strings approved by the user.

    Returns:
        The number of redaction rectangles applied.
    """

    entities = _prepare_entities(approved_entities)
    if not entities:
        raise ValueError("At least one approved entity is required.")

    annotation_count = 0
    with fitz.open(input_path) as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")

        for page in document:
            page_annotation_count = 0
            for entity in entities:
                for rectangle in page.search_for(entity):
                    page.add_redact_annot(rectangle, fill=(0.0, 0.0, 0.0))
                    page_annotation_count += 1

            if page_annotation_count:
                page.apply_redactions()
                annotation_count += page_annotation_count

        document.save(
            output_path,
            garbage=4,
            clean=True,
            deflate=True,
        )

    return annotation_count


def _normalize_ocr_token(value: str) -> str:
    """Normalize OCR text for punctuation-tolerant entity matching."""

    return re.sub(r"[^0-9a-z]+", "", value.casefold())


def _build_ocr_targets(entities: Sequence[str]) -> tuple[tuple[str, int], ...]:
    """Build compact OCR targets and bounded token spans."""

    targets: list[tuple[str, int]] = []
    for entity in entities:
        compact = _normalize_ocr_token(entity)
        if not compact:
            continue
        word_count = len(re.findall(r"\S+", entity))
        targets.append((compact, min(max(word_count + 2, 3), 8)))
    return tuple(targets)


def _find_ocr_redaction_boxes(
    ocr_data: dict[str, list[object]],
    targets: Sequence[tuple[str, int]],
) -> set[tuple[int, int, int, int]]:
    """Find exact OCR word boxes whose contiguous text matches an entity."""

    tokens: list[dict[str, object]] = []
    text_values = ocr_data.get("text", [])

    for index, raw_text in enumerate(text_values):
        normalized = _normalize_ocr_token(str(raw_text))
        if not normalized:
            continue

        confidence_values = ocr_data.get("conf", [])
        if index < len(confidence_values):
            try:
                if float(confidence_values[index]) < 0:
                    continue
            except (TypeError, ValueError):
                pass

        tokens.append(
            {
                "normalized": normalized,
                "box": (
                    int(ocr_data["left"][index]),
                    int(ocr_data["top"][index]),
                    int(ocr_data["width"][index]),
                    int(ocr_data["height"][index]),
                ),
                "line": (
                    int(ocr_data["block_num"][index]),
                    int(ocr_data["par_num"][index]),
                    int(ocr_data["line_num"][index]),
                ),
            }
        )

    boxes: set[tuple[int, int, int, int]] = set()
    for target, maximum_span in targets:
        for start_index, start_token in enumerate(tokens):
            candidate = ""
            start_line = start_token["line"]
            upper_bound = min(len(tokens), start_index + maximum_span)

            for token_index in range(start_index, upper_bound):
                token = tokens[token_index]
                if token["line"] != start_line:
                    break
                candidate += str(token["normalized"])

                if candidate == target:
                    for matched_index in range(start_index, token_index + 1):
                        boxes.add(tokens[matched_index]["box"])  # type: ignore[arg-type]
                    break
                if len(candidate) >= len(target):
                    break

    return boxes


def _write_image_page_as_pdf(
    image: Image.Image,
    page_pdf_path: Path,
    width_points: float,
    height_points: float,
    temporary_directory: Path,
) -> None:
    """Write a raster page into an exactly sized single-page PDF."""

    image_path = temporary_directory / f"{page_pdf_path.stem}.png"
    try:
        image.save(image_path, "PNG", compress_level=6)
        page_document = fitz.open()
        try:
            page = page_document.new_page(width=width_points, height=height_points)
            page.insert_image(page.rect, filename=str(image_path), keep_proportion=False)
            page_document.save(page_pdf_path, garbage=4, clean=True, deflate=True)
        finally:
            page_document.close()
    finally:
        image_path.unlink(missing_ok=True)


def redact_scanned_pdf(
    input_path: Path,
    output_path: Path,
    approved_entities: Sequence[str],
) -> int:
    """Physically redact a scanned PDF by replacing matching image pixels.

    Each source page is rendered and processed independently. The redacted page
    is immediately written as a temporary one-page PDF, and all image objects and
    OCR dictionaries are released before the next page is loaded.

    Args:
        input_path: Canonical path of the source PDF.
        output_path: Destination path for the redacted PDF.
        approved_entities: Exact entity strings approved by the user.

    Returns:
        The number of OCR word rectangles painted solid black.
    """

    entities = _prepare_entities(approved_entities)
    if not entities:
        raise ValueError("At least one approved entity is required.")

    targets = _build_ocr_targets(entities)
    if not targets:
        raise ValueError("Approved entities do not contain searchable characters.")

    page_count = _get_page_count(input_path)
    page_dimensions = _get_page_dimensions(input_path)
    if len(page_dimensions) != page_count:
        raise RuntimeError("PDF page metadata is inconsistent.")
    rectangle_count = 0

    with tempfile.TemporaryDirectory(prefix="pdf-smart-redactor-pages-") as temporary_name:
        temporary_directory = Path(temporary_name)
        page_pdf_paths: list[Path] = []

        for page_number in range(1, page_count + 1):
            image: Image.Image | None = None
            rendered_path: Path | None = None
            ocr_data: dict[str, list[object]] | None = None
            drawing_context: ImageDraw.ImageDraw | None = None

            try:
                image, rendered_path = _render_single_page(
                    input_path,
                    page_number,
                    temporary_directory,
                )
                ocr_data = pytesseract.image_to_data(
                    image,
                    output_type=Output.DICT,
                    timeout=OCR_TIMEOUT_SECONDS,
                )
                boxes = _find_ocr_redaction_boxes(ocr_data, targets)
                drawing_context = ImageDraw.Draw(image)

                for left, top, width, height in boxes:
                    drawing_context.rectangle(
                        (left, top, left + width, top + height),
                        fill="#000000",
                    )

                rectangle_count += len(boxes)
                page_pdf_path = temporary_directory / f"redacted-page-{page_number:05d}.pdf"
                page_width, page_height = page_dimensions[page_number - 1]
                _write_image_page_as_pdf(
                    image,
                    page_pdf_path,
                    page_width,
                    page_height,
                    temporary_directory,
                )
                page_pdf_paths.append(page_pdf_path)
            finally:
                if drawing_context is not None:
                    del drawing_context
                if image is not None:
                    image.close()
                if rendered_path is not None:
                    rendered_path.unlink(missing_ok=True)
                if ocr_data is not None:
                    ocr_data.clear()
                del ocr_data
                del image
                gc.collect()

        output_document = fitz.open()
        try:
            for page_pdf_path in page_pdf_paths:
                with fitz.open(page_pdf_path) as page_document:
                    output_document.insert_pdf(page_document)
            output_document.save(
                output_path,
                garbage=4,
                clean=True,
                deflate=True,
            )
        finally:
            output_document.close()
            gc.collect()

    return rectangle_count
