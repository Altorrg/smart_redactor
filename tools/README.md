# Local OCR Tools

This application can use approved portable OCR tools without modifying the
system `PATH`.

Place Tesseract OCR files in this layout:

```text
tools/tesseract/tesseract.exe
tools/tesseract/tessdata/
```

Poppler is no longer required. PyMuPDF performs bounded page rendering.
Put `hun.traineddata` and `eng.traineddata` in `tools/tessdata` and retain
the accompanying Apache-2.0 license. The reviewed test bundle includes them.

The files must come from a source approved by the organization. The launcher
does not download tools, modify `PATH`, write registry settings, or make
external network requests.

Absolute locations outside the project can also be supplied without changing
`PATH` by setting `PDF_REDACTOR_TESSERACT_PATH` to `tesseract.exe` and
`PDF_REDACTOR_TESSDATA_PATH` to the language-model directory before launch.
The default OCR language is `hun+eng`; use `PDF_REDACTOR_OCR_LANG` to change it.

