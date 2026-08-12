# Local OCR Tools

This application can use approved portable OCR tools without modifying the
system `PATH`.

Place Tesseract OCR files in this layout:

```text
tools/tesseract/tesseract.exe
tools/tesseract/tessdata/
```

Place Poppler files in either supported layout:

```text
tools/poppler/Library/bin/pdfinfo.exe
tools/poppler/Library/bin/pdftoppm.exe
```

or:

```text
tools/poppler/bin/pdfinfo.exe
tools/poppler/bin/pdftoppm.exe
```

The files must come from a source approved by the organization. The launcher
does not download tools, modify `PATH`, write registry settings, or make
external network requests.

Absolute locations outside the project can also be supplied without changing
`PATH` by setting `PDF_REDACTOR_TESSERACT_PATH` to `tesseract.exe` and
`PDF_REDACTOR_POPPLER_PATH` to the Poppler binary directory before launch.
