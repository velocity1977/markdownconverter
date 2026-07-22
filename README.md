# ConvertDown

**ConvertDown** is a powerful desktop utility built with Python and PyQt6 that flawlessly converts documents and data files into clean, readable Markdown. 

It handles multiple formats in bulk, extracts images inline, and automatically fixes garbled legacy symbol fonts.

## Supported Formats
* **PDF** (Processed via `pymupdf4llm`)
* **DOCX, PPTX, XLSX** (Processed via Microsoft's `MarkItDown`)
* **HTML, CSV, JSON, XML, TXT** (Processed via `MarkItDown`)

## Key Features
* **Bulk Processing**: Drag and drop entire folders of documents, and ConvertDown will queue and process them asynchronously.
* **Inline Image Extraction**: Optionally extract figures and images from PDF, DOCX, and PPTX files and embed them natively in the resulting Markdown (saved in a `<filename>_assets` directory).
* **Formula & Symbol Repair**: Automatically fixes angle signs, Greek letters, and other math symbols in older PDFs that were rendered via legacy Private-Use-Area Symbol fonts.
* **Encrypted PDF Support**: Pass a single password to decrypt and convert secured bank or tax statements in bulk.
* **Native OS Theming**: Automatically detects and matches your Windows 10/11 Light or Dark mode.

## Installation / Running from Source

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

## Building for Release (Windows)

To distribute ConvertDown as a standalone Windows application:

1. **Build the Executable:**
   Use PyInstaller to compile the source into an executable and an `_internal` dependency folder.
   ```bash
   pyinstaller ConvertDown.spec
   ```
   *(This places the build inside the `dist/ConvertDown` directory).*

2. **Create the Installer:**
   Download and install [Inno Setup](https://jrsoftware.org/isinfo.php). Double-click the provided `setup.iss` file in the project root, and click **Compile**. This will pack the executable and all its dependencies into a single, professional `ConvertDown_Setup.exe` installer inside an `Output/` folder.

## Technologies Used
* **UI**: PyQt6
* **PDF Conversion**: `pymupdf4llm`
* **Office/Data Conversion**: `markitdown`
* **Packaging**: `PyInstaller` & `Inno Setup`
