# ConvertDown

**ConvertDown** is a standalone, GUI-based Windows utility designed to help general users easily convert documents and data files into Markdown format. 

**Objective:** The primary goal is to provide a simple, drag-and-drop interface for users who need Markdown conversions but do not want to interact with command-line tools or write code. While the conversion is not perfect and has limitations with highly complex document layouts, it works reliably for the vast majority of standard use cases.

**Licensing Note:** This project uses [pymupdf4llm](https://github.com/pymupdf/pymupdf4llm) for PDF conversions. `pymupdf4llm` (and its underlying `PyMuPDF` library) is strictly licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0)](https://github.com/pymupdf/PyMuPDF/blob/main/LICENSE). In compliance with the AGPL requirements regarding derivative works and distribution, the complete source code for ConvertDown is open-sourced and published in this repository.

## Supported Formats
* **PDF** (via `pymupdf4llm`)
* **DOCX, PPTX, XLSX** (via `markitdown`)
* **HTML, CSV, JSON, XML, TXT** (via `markitdown`)

## Features
* **Batch Processing**: Queue and process multiple files or directories asynchronously.
* **Image Extraction**: Option to extract figures and images from PDF, DOCX, and PPTX files and embed them in the resulting Markdown (saved to a `<filename>_assets` directory).
* **Symbol Repair**: Basic substitution for legacy Private-Use-Area Symbol fonts in PDFs (e.g., angle signs, Greek letters) to standard Unicode characters.
* **Encrypted PDF Support**: Pass a single password to decrypt and convert secured files in a batch.
* **OS Theming**: Automatically detects and matches Windows Light or Dark mode.

## Local Setup & Development

**Requirements:** Python 3.10+

1. Clone this repository:
   ```bash
   git clone https://github.com/YOUR-USERNAME/markdownConverter.git
   cd markdownConverter
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the application:
   ```bash
   python ui_main.py
   ```

## Building for Windows

If you need to distribute the application as a standalone executable:

1. **Build the Application:**
   Compile the source into an executable directory using PyInstaller.
   ```bash
   pyinstaller ConvertDown.spec
   ```
   This will output the build to the `dist/ConvertDown` directory.

2. **Create the Installer:**
   An Inno Setup script (`setup.iss`) is included in the repository. Open the script with [Inno Setup](https://jrsoftware.org/isinfo.php) and compile it to generate a `ConvertDown_Setup.exe` installer.

## Built With
* [PyQt6](https://pypi.org/project/PyQt6/) - UI Framework
* [pymupdf4llm](https://github.com/pymupdf/pymupdf4llm) - PDF to Markdown conversion (AGPL-3.0)
* [markitdown](https://github.com/microsoft/markitdown) - Office and data file conversion
