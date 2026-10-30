"""Native-text and OCR-based physical PDF redaction functions."""

from __future__ import annotations

import gc
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Literal, Sequence

import pymupdf as fitz
import pytesseract
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
OCR_LANGUAGE = os.environ.get("PDF_REDACTOR_OCR_LANG", "hun+eng")
OCR_CONFIG = ""
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

    global LOCAL_TESSERACT_PATH, LOCAL_POPPLER_PATH, OCR_CONFIG

    tesseract_defaults = [
        PROJECT_ROOT / "tools" / "tesseract" / "tesseract.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PDF24" / "tesseract" / "tesseract.exe",
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
    tessdata = os.environ.get("PDF_REDACTOR_TESSDATA_PATH", "").strip()
    if not tessdata and (PROJECT_ROOT / "tools" / "tessdata").is_dir():
        tessdata = str(PROJECT_ROOT / "tools" / "tessdata")
    # Windows shlex in pytesseract can preserve literal quotes in --tessdata-dir.
    # Use Tesseract's documented per-process environment setting instead.
    OCR_CONFIG = ""
    if tessdata:
        os.environ["TESSDATA_PREFIX"] = str(Path(tessdata).resolve())

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
    # Rendering uses the already required PyMuPDF: no separate Poppler install.
    languages: list[str] = []
    if LOCAL_TESSERACT_PATH is not None or tesseract_command:
        try:
            command = [pytesseract.pytesseract.tesseract_cmd, "--list-langs"]
            if tessdata:
                command.extend(["--tessdata-dir", str(Path(tessdata).resolve())])
            listed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=10, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            # Some Windows builds print the path header in the ANSI code page.
            # Language identifiers are ASCII; never fail startup decoding that header.
            languages = [line.strip() for line in listed.stdout.decode("utf-8", errors="replace").splitlines()
                if re.fullmatch(r"[A-Za-z0-9_/]+", line.strip())]
            missing_tools.extend(f"OCR language: {lang}" for lang in OCR_LANGUAGE.split("+") if lang not in languages)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            missing_tools.append("working Tesseract language data")

    return {
        "ready": not missing_tools,
        "missing_tools": missing_tools,
        "tesseract_path": str(LOCAL_TESSERACT_PATH or tesseract_command or ""),
        "poppler_path": str(LOCAL_POPPLER_PATH or ("PATH" if poppler_on_path else "")),
        "ocr_language": OCR_LANGUAGE,
        "available_languages": languages,
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
    """Return a bounded page count using the existing PDF engine."""

    with fitz.open(pdf_path) as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")
        if document.is_form_pdf:
            raise ValueError("Interactive PDF forms require a reviewed flattened copy first.")
        page_count = document.page_count
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
        if document.is_form_pdf:
            raise ValueError("Interactive PDF forms require a reviewed flattened copy first.")
        if document.page_count < 1:
            raise ValueError("The PDF does not contain any pages.")

        for page in document:
            # A searchable heading or hidden OCR layer does not prove that image text
            # is covered. Any raster content takes the conservative OCR/raster route.
            if page.get_images(full=True):
                return False
            text = page.get_text("text").strip()
            if text:
                found_text = True
                continue
    return found_text


def _render_single_page(
    pdf_path: Path,
    page_number: int,
    output_directory: Path,
) -> tuple[Image.Image, Path]:
    """Render one bounded-size PDF page and return its loaded Pillow image."""

    rendered_path = output_directory / f"source-page-{page_number:05d}.png"
    with fitz.open(pdf_path) as document:
        page = document[page_number - 1]
        scale = MAX_RENDER_DIMENSION / max(page.rect.width, page.rect.height)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    return image, rendered_path


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
                    lang=OCR_LANGUAGE,
                    config=OCR_CONFIG,
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
    found: set[str] = set()
    with fitz.open(input_path) as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")
        if document.is_form_pdf:
            raise ValueError("Interactive PDF forms require a reviewed flattened copy first.")

        for page in document:
            page_annotation_count = 0
            for entity in entities:
                rectangles = _native_entity_rectangles(page, entity)
                if rectangles:
                    found.add(_entity_key(entity))
                for rectangle in rectangles:
                    page.add_redact_annot(rectangle, fill=(0.0, 0.0, 0.0))
                    page_annotation_count += 1

            if page_annotation_count:
                page.apply_redactions()
                annotation_count += page_annotation_count

            # scrub(reset_responses=True) clears annotation replies, not the
            # original note/free-text content. Remove annotations explicitly:
            # otherwise approved text can survive outside extracted page text.
            for annotation in list(page.annots() or []):
                page.delete_annot(annotation)

        _require_all_entities(entities, found)
        # Do not retain metadata, comments, attachments, hidden text or JavaScript
        # that could still carry the approved values. Visible forms are refused.
        document.scrub()
        document.set_toc([])
        _verify_native_text_removed(document, entities)
        document.save(
            output_path,
            garbage=4,
            clean=True,
            deflate=True,
        )

    return annotation_count


def _normalize_ocr_token(value: str) -> str:
    """Normalize OCR text for punctuation-tolerant entity matching."""

    value = unicodedata.normalize("NFKC", value).casefold().replace("−", "-").replace("’", "'")
    value = "".join(c for c in value if c.isalnum() or c in ",.+-'$€£&")
    return re.sub(r"(?<!\d)[,.]|[,.](?!\d)", "", value)


def _entity_key(entity: str) -> str:
    return " ".join(part for word in entity.split() if (part := _normalize_ocr_token(word)))


def _require_all_entities(entities: Sequence[str], found: set[str]) -> None:
    missing = [entity for entity in entities if _entity_key(entity) not in found]
    if missing:
        raise ValueError("Export stopped: some approved values were not located. Review the selection or OCR. Missing: " + "; ".join(missing))


def _verify_native_text_removed(document: fitz.Document, entities: Sequence[str]) -> None:
    """Check extracted text independently of word-box matching before saving.

    Ambiguous layout can leave a repeated value behind even when another
    occurrence was found. Refuse that export instead of treating one match as
    evidence that every occurrence was removed. This is not an OCR guarantee.
    """
    keys = [(entity, _entity_key(entity)) for entity in entities]
    for page in document:
        text = re.sub(r"(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)", "", page.get_text("text"))
        normalized = _entity_key(text)
        remaining = [entity for entity, key in keys if key and
            re.search(r"(?<!\S)" + re.escape(key) + r"(?!\S)", normalized)]
        if remaining:
            raise ValueError("Export stopped: approved text remains after redaction. Review this page or use a reviewed raster copy. Remaining: " + "; ".join(remaining))


def _native_entity_rectangles(page: fitz.Page, entity: str) -> list[fitz.Rect]:
    """Unicode casefold and whole-word matching; never redact Anna inside Annabelle."""
    tokens = [{"normalized": _entity_key(w[4]), "box": (w[0], w[1], w[2]-w[0], w[3]-w[1]), "line": w[5:7]}
        for w in page.get_text("words", sort=True) if _entity_key(w[4])]
    boxes = _matching_boxes(tokens, ((_entity_key(entity), min(max(len(entity.split())+4, 6), 64)),))
    return [fitz.Rect(x, y, x+w, y+h) for x, y, w, h in boxes]


def _continues_text(previous: dict, current: dict) -> bool:
    x, y, w, h = previous["box"]; nx, ny, nw, nh = current["box"]
    if previous["line"] == current["line"]:
        return nx - (x+w) <= 3 * max(h, nh)
    return (previous["line"][:-1] == current["line"][:-1]
        and current["line"][-1] == previous["line"][-1]+1 and 0 < ny-y <= 2.5*max(h, nh))


def _matching_boxes(tokens: Sequence[dict], targets: Sequence[tuple[str, int]], matched: set[str] | None = None) -> set:
    boxes: set = set()
    for target, maximum_span in targets:
        for start in range(len(tokens)):
            candidates = {""}
            for end in range(start, min(len(tokens), start+maximum_span)):
                token = tokens[end]
                if end > start and not _continues_text(tokens[end-1], token):
                    break
                wrapped = end > start and tokens[end-1]["line"] != token["line"]
                next_candidates = set()
                for candidate in candidates:
                    next_candidates.add(candidate + (" " if candidate else "") + token["normalized"])
                    if wrapped and candidate.endswith("-") and len(candidate)>1 and candidate[-2].isalpha():
                        next_candidates.add(candidate + token["normalized"])
                        next_candidates.add(candidate[:-1] + token["normalized"])
                candidates = {c for c in next_candidates if target.startswith(c) or
                    (c.endswith("-") and len(c)>1 and c[-2].isalpha() and target.startswith(c[:-1]))}
                if target in candidates:
                    boxes.update(t["box"] for t in tokens[start:end+1])
                    if matched is not None:
                        matched.add(target)
                    break
                if not candidates:
                    break
    return boxes


def _build_ocr_targets(entities: Sequence[str]) -> tuple[tuple[str, int], ...]:
    """Build compact OCR targets and bounded token spans."""

    targets: list[tuple[str, int]] = []
    for entity in entities:
        compact = _entity_key(entity)
        if not compact:
            continue
        word_count = len(re.findall(r"\S+", entity))
        targets.append((compact, min(max(word_count + 2, 3), 64)))
    return tuple(targets)


def _find_ocr_redaction_boxes(
    ocr_data: dict[str, list[object]],
    targets: Sequence[tuple[str, int]],
    matched_targets: set[str] | None = None,
) -> set[tuple[int, int, int, int]]:
    """Find exact OCR word boxes whose contiguous text matches an entity."""

    tokens: list[dict[str, object]] = []
    text_values = ocr_data.get("text", [])

    for index, raw_text in enumerate(text_values):
        normalized = _entity_key(str(raw_text))
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

    return _matching_boxes(tokens, targets, matched_targets)


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
    found: set[str] = set()

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
                    lang=OCR_LANGUAGE,
                    config=OCR_CONFIG,
                    output_type=Output.DICT,
                    timeout=OCR_TIMEOUT_SECONDS,
                )
                boxes = _find_ocr_redaction_boxes(ocr_data, targets, found)
                drawing_context = ImageDraw.Draw(image)

                for left, top, width, height in boxes:
                    drawing_context.rectangle(
                        (max(0, left - 2), max(0, top - 2), left + width + 2, top + height + 2),
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

        _require_all_entities(entities, found)
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

