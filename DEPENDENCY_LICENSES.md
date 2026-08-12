# Third-Party Dependency Licenses

PDF Smart Redactor GUI performs all processing locally and does not make external API calls. No database is used. The application relies on the third-party components listed below. Distributors must preserve the applicable copyright notices, license notices, disclaimers, and source-code obligations for the exact versions they ship.

This file is an attribution and compliance summary. A distribution should also include the complete license text supplied by each dependency and retain any upstream `LICENSE`, `COPYING`, or `NOTICE` files.

## PyMuPDF / MuPDF

- Component used: PyMuPDF, imported as `fitz`, and its MuPDF engine.
- License: GNU Affero General Public License version 3.0 (AGPL-3.0), or a separately purchased commercial MuPDF license from Artifex.
- Copyright holder: Artifex Software, Inc. and PyMuPDF contributors, as identified by the distributed package.
- Attribution and distribution requirements: Preserve copyright and license notices, include the complete AGPL-3.0 text, identify modifications, provide the corresponding source code for the covered work under AGPL-3.0, and provide the required installation information when applicable. Users interacting with a modified covered work over a network must be offered the corresponding source as required by AGPL section 13.
- Commercial alternative: A distributor that cannot satisfy the AGPL-3.0 obligations must obtain and comply with an appropriate commercial MuPDF license before distribution.

## Tesseract OCR

- Component used: The locally installed Tesseract OCR executable and libraries.
- License: Apache License 2.0.
- Copyright holder: Google LLC and Tesseract contributors, as identified by the distributed project.
- Attribution and distribution requirements: Include a copy of the Apache License 2.0, preserve copyright, patent, trademark, and attribution notices, state significant modifications, and include the upstream `NOTICE` file when one is supplied. Do not imply endorsement and do not use contributor trademarks except as permitted by law.

## pytesseract

- Component used: `pytesseract`, the Python wrapper used to invoke local Tesseract OCR.
- License: Apache License 2.0 for current releases beginning with pytesseract 0.3.1. The project specification's GPL-3.0 label is not used because it conflicts with the upstream license file and package metadata.
- Copyright holder: pytesseract authors and contributors, as identified by the distributed package.
- Attribution and distribution requirements: Include a copy of the Apache License 2.0, preserve copyright, patent, trademark, and attribution notices, state significant modifications, and include any upstream `NOTICE` file supplied with the distributed release.

## pdf2image

- Component used: `pdf2image`, used to render PDF pages through a local Poppler installation.
- License: MIT License.
- Copyright holder: Edouard Belval and pdf2image contributors, as identified by the distributed package.
- Attribution and distribution requirements: Include the upstream copyright notice and the complete MIT permission and warranty disclaimer in all copies or substantial portions of the software.
- Additional runtime notice: Poppler is a separate system dependency. A distributor that bundles Poppler must independently review and satisfy the license terms of the exact Poppler build and its linked libraries.

## Pillow

- Component used: Pillow, imported through the `PIL` package.
- License: Historical Permission Notice and Disclaimer (HPND License).
- Copyright holder: Secret Labs AB, Fredrik Lundh, Alex Clark, and Pillow contributors, as identified by the distributed package.
- Attribution and distribution requirements: Preserve the HPND copyright notice, permission notice, and warranty disclaimer in source and binary redistributions. The names of the copyright holders may not be used to promote derived products without specific prior written permission.

## Eel

- Component used: Eel, used to connect the local Python process to the HTML and JavaScript interface.
- License: MIT License.
- Copyright holder: Chris Knott and Eel contributors, as identified by the distributed package.
- Attribution and distribution requirements: Include the upstream copyright notice and the complete MIT permission and warranty disclaimer in all copies or substantial portions of the software.

## Distribution Checklist

1. Record and pin the exact dependency versions included in each release.
2. Bundle the complete corresponding license text and upstream notice files for every shipped dependency.
3. Provide source code and installation information required by AGPL-3.0, or obtain an appropriate commercial MuPDF license.
4. Review licenses for transitive and system dependencies, including Poppler and any bundled OCR language data.
5. Keep the in-application third-party license link visible and keep this file with every binary and source distribution.
