import sys
import os
import ctypes
import ctypes.wintypes
import psutil
import logging
from pathlib import Path

if sys.platform == "win32":
    import winreg

# Setup file logging
logging.basicConfig(
    filename='app.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QFileDialog,
    QProgressBar, QHeaderView, QMessageBox, QCheckBox, QStatusBar, QLineEdit
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPalette, QIcon, QAction

from workers import ConversionWorker
from router import SUPPORTED_EXTENSIONS
from collections import Counter


def resource_path(relative_path: str) -> str:
    """
    Resolve a bundled resource's path whether running from source (python
    ui_main.py) or from a frozen PyInstaller build. PyInstaller unpacks
    `datas` entries next to sys._MEIPASS at runtime; when running from
    source there is no such attribute, so we fall back to the folder this
    file lives in.
    """
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def detect_windows_theme() -> str:
    """
    Reads the user's actual Windows Settings > Personalization > Colors
    choice (dark/light) so the app matches it instead of always forcing one
    theme regardless of what the user picked at the OS level. Returns "dark"
    or "light"; defaults to "dark" (this app's original look) if the
    registry value is missing (older Windows versions before this setting
    existed) or unreadable for any reason.
    """
    if sys.platform != "win32":
        return "dark"
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value == 1 else "dark"
    except (FileNotFoundError, OSError):
        logger.debug("Could not read Windows theme preference; defaulting to dark", exc_info=True)
        return "dark"


def set_titlebar_theme(hwnd: int, dark: bool) -> None:
    """
    The app's QSS colors the window body, but that can't reach the OS-drawn
    title bar (minimize/maximize/close chrome) -- Qt stylesheets don't apply
    there. Without this, the title bar stays whatever the system default is,
    creating a visible light/dark seam at the top of the window regardless
    of which theme the body actually uses. DWMWA_USE_IMMERSIVE_DARK_MODE is
    the documented DWM attribute for this; its numeric value changed once
    early on (19 pre-20H1, 20 from 20H1 onward), so we try the current value
    first and fall back to the legacy one. No-op (silently) on anything that
    isn't Windows 10 1809+ / 11.
    """
    if sys.platform != "win32":
        return
    try:
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE, then legacy fallback
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.wintypes.HWND(hwnd),
                attribute,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if result == 0:  # S_OK
                break
    except Exception:
        logger.debug("Title bar theme not applied (non-Windows or unsupported build)", exc_info=True)


# Two full theme variants, picked at startup based on detect_windows_theme().
# Kept as plain strings (not computed per-widget) so apply_styles() stays a
# single setStyleSheet() call, and so switching theme later only ever means
# swapping which constant gets passed in -- no per-widget style scattered
# around setup_ui() to keep in sync.
DARK_STYLESHEET = """
    QMainWindow {
        background-color: #1E1E1E;
    }
    #titleLabel {
        font-size: 18px;
        font-weight: bold;
        color: #E0E0E0;
    }
    #outputDirLabel {
        color: #AAAAAA;
    }
    QMenuBar {
        background-color: #1E1E1E;
        color: #D4D4D4;
        border-bottom: 1px solid #3F3F46;
    }
    QMenuBar::item {
        background-color: transparent;
        padding: 4px 10px;
    }
    QMenuBar::item:selected {
        background-color: #3F3F46;
    }
    QMenu {
        background-color: #252526;
        color: #D4D4D4;
        border: 1px solid #3F3F46;
    }
    QMenu::item:selected {
        background-color: #0E639C;
    }
    QTableWidget {
        background-color: #252526;
        color: #D4D4D4;
        gridline-color: #3F3F46;
        border: 1px solid #3F3F46;
        border-radius: 4px;
    }
    QHeaderView::section {
        background-color: #333333;
        color: white;
        padding: 4px;
        border: 1px solid #3F3F46;
    }
    QPushButton {
        background-color: #0E639C;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 4px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #1177BB;
    }
    QPushButton:disabled {
        background-color: #555555;
        color: #AAAAAA;
    }
    QProgressBar {
        border: 1px solid #3F3F46;
        border-radius: 4px;
        text-align: center;
        background-color: #252526;
        color: white;
    }
    QProgressBar::chunk {
        background-color: #0E639C;
    }
    QStatusBar {
        background-color: #1E1E1E;
        color: #00E676;
        border-top: 1px solid #3F3F46;
    }
    QStatusBar QLabel {
        color: #00E676;
        font-size: 12px;
        font-weight: bold;
        padding: 0 8px;
    }
    QCheckBox {
        color: #D4D4D4;
    }
    QLineEdit {
        background-color: #2D2D2D;
        color: #D4D4D4;
        border: 1px solid #3F3F46;
        border-radius: 4px;
        padding: 6px 8px;
    }
    QLineEdit:focus {
        border: 1px solid #0E639C;
    }
"""

LIGHT_STYLESHEET = """
    QMainWindow {
        background-color: #F3F3F3;
    }
    #titleLabel {
        font-size: 18px;
        font-weight: bold;
        color: #1F1F1F;
    }
    #outputDirLabel {
        color: #5F5F5F;
    }
    QMenuBar {
        background-color: #F3F3F3;
        color: #1F1F1F;
        border-bottom: 1px solid #D0D0D0;
    }
    QMenuBar::item {
        background-color: transparent;
        padding: 4px 10px;
    }
    QMenuBar::item:selected {
        background-color: #E0E0E0;
    }
    QMenu {
        background-color: #FFFFFF;
        color: #1F1F1F;
        border: 1px solid #D0D0D0;
    }
    QMenu::item:selected {
        background-color: #0E639C;
        color: white;
    }
    QTableWidget {
        background-color: #FFFFFF;
        color: #1F1F1F;
        gridline-color: #D0D0D0;
        border: 1px solid #D0D0D0;
        border-radius: 4px;
    }
    QHeaderView::section {
        background-color: #E5E5E5;
        color: #1F1F1F;
        padding: 4px;
        border: 1px solid #D0D0D0;
    }
    QPushButton {
        background-color: #0E639C;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 4px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #1177BB;
    }
    QPushButton:disabled {
        background-color: #CCCCCC;
        color: #888888;
    }
    QProgressBar {
        border: 1px solid #D0D0D0;
        border-radius: 4px;
        text-align: center;
        background-color: #FFFFFF;
        color: #1F1F1F;
    }
    QProgressBar::chunk {
        background-color: #0E639C;
    }
    QStatusBar {
        background-color: #F3F3F3;
        color: #0E7A3C;
        border-top: 1px solid #D0D0D0;
    }
    QStatusBar QLabel {
        color: #0E7A3C;
        font-size: 12px;
        font-weight: bold;
        padding: 0 8px;
    }
    QCheckBox {
        color: #1F1F1F;
    }
    QLineEdit {
        background-color: #FFFFFF;
        color: #1F1F1F;
        border: 1px solid #D0D0D0;
        border-radius: 4px;
        padding: 6px 8px;
    }
    QLineEdit:focus {
        border: 1px solid #0E639C;
    }
"""


class MarkdownConverterApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ConvertDown")
        self.resize(900, 600)
        self.setAcceptDrops(True)

        # Detected once at startup rather than polled continuously: Windows
        # doesn't notify running apps live when the user flips light/dark in
        # Settings, so there's no simple event to hook for that anyway --
        # matching whatever the setting was when the app launched is the
        # standard behavior most native apps follow too.
        self.theme = detect_windows_theme()

        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            logger.warning(f"icon.ico not found at {icon_path} -- run generate_icon.py once")
        
        self.output_dir = None  # None means "Same as Input File"
        
        self.worker = None
        
        self.setup_menu_bar()
        self.setup_ui()
        self.apply_styles()
        
        # Timer for memory analytics
        self.analytics_timer = QTimer(self)
        self.analytics_timer.timeout.connect(self.update_analytics)
        self.analytics_timer.start(1000) # Update every 1 second

    def showEvent(self, event):
        super().showEvent(event)
        # winId() only returns a valid native handle once the window has
        # actually been created by the OS, so this has to run after show()
        # rather than in __init__. Guarded to only run once even though
        # showEvent can fire more than once (e.g. after minimize/restore).
        if not getattr(self, "_titlebar_theme_applied", False):
            set_titlebar_theme(int(self.winId()), dark=(self.theme == "dark"))
            self._titlebar_theme_applied = True

    def setup_menu_bar(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")

        action_add_files = QAction("&Add Files...", self)
        action_add_files.triggered.connect(self.add_files_dialog)
        file_menu.addAction(action_add_files)

        action_add_folder = QAction("Add &Folder...", self)
        action_add_folder.triggered.connect(self.add_folder_dialog)
        file_menu.addAction(action_add_folder)

        file_menu.addSeparator()

        action_exit = QAction("E&xit", self)
        action_exit.triggered.connect(self.close)
        file_menu.addAction(action_exit)

        help_menu = menu_bar.addMenu("&Help")
        action_about = QAction("&About", self)
        action_about.triggered.connect(self.show_about_dialog)
        help_menu.addAction(action_about)

    def show_about_dialog(self):
        QMessageBox.about(
            self,
            "About ConvertDown",
            "<h3>ConvertDown</h3>"
            "<p>Converts PDF, DOCX, XLSX, PPTX, HTML, CSV, JSON, XML, and TXT "
            "files to Markdown.</p>"
            "<p>PDFs are processed with pymupdf4llm; other formats with "
            "Microsoft's MarkItDown.</p>"
        )

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title Label
        title = QLabel("Drag & Drop Files Here (PDF, DOCX, XLSX, etc.)")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # File/Folder Selection Buttons
        add_layout = QHBoxLayout()
        add_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.btn_add_files = QPushButton("Add Files")
        self.btn_add_files.setMinimumWidth(120)
        self.btn_add_files.clicked.connect(self.add_files_dialog)
        add_layout.addWidget(self.btn_add_files)
        
        self.btn_add_folder = QPushButton("Add Folder")
        self.btn_add_folder.setMinimumWidth(120)
        self.btn_add_folder.clicked.connect(self.add_folder_dialog)
        add_layout.addWidget(self.btn_add_folder)
        
        layout.addLayout(add_layout)

        # File Table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Filename", "Type", "Status", "Output Path"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # Analytics -- shown in a real QStatusBar rather than a custom
        # floating QFrame. Windows renders a QStatusBar with proper native
        # chrome docked at the bottom of the window, which is where a user's
        # eye already expects transient/status info to live, instead of a
        # manually-styled box sitting mid-layout.
        self.lbl_total_files = QLabel("Total Files: 0")
        self.lbl_processed = QLabel("Processed: 0")
        self.lbl_memory = QLabel("RAM Usage: 0 MB")

        status_bar = QStatusBar()
        for lbl in (self.lbl_total_files, self.lbl_processed, self.lbl_memory):
            status_bar.addPermanentWidget(lbl)
        self.setStatusBar(status_bar)

        # Controls
        controls_layout = QHBoxLayout()
        
        self.btn_output_dir = QPushButton("Select Output Folder")
        self.btn_output_dir.clicked.connect(self.select_output_dir)
        controls_layout.addWidget(self.btn_output_dir)
        
        self.lbl_output_dir = QLabel("Output: Same as Input Folder")
        self.lbl_output_dir.setObjectName("outputDirLabel")
        controls_layout.addWidget(self.lbl_output_dir)
        
        controls_layout.addStretch()

        # Embeds figures/images found in the source file inline in the
        # generated markdown, as a sibling "<name>_assets/" folder. Covers
        # PDF (via pymupdf4llm's write_images), and DOCX/PPTX (via
        # office_images.py, since MarkItDown itself doesn't actually extract
        # images for those formats -- see that module for what was broken).
        self.chk_include_images = QCheckBox("Include images (PDF, DOCX, PPTX)")
        self.chk_include_images.setToolTip(
            "Embeds figures/images found in the source file inline in the\n"
            "markdown. Saves them to a '<filename>_assets' folder next to\n"
            "the output. Supported for PDF, DOCX, and PPTX."
        )
        controls_layout.addWidget(self.chk_include_images)

        # Fixes math/Greek symbols garbled by Adobe-Symbol-font Private-Use-
        # Area encoding (see symbol_fonts.py). This is a plain-Unicode fix,
        # not real LaTeX reconstruction -- multi-line fraction/stack layout
        # is a separate, much bigger problem this doesn't attempt.
        self.chk_include_formulae = QCheckBox("Fix formula symbols (PDF)")
        self.chk_include_formulae.setToolTip(
            "Repairs angle signs, Greek letters, sqrt, and other math symbols\n"
            "that some PDFs render via a legacy Symbol font (shows as correct\n"
            "Unicode characters, not full LaTeX layout)."
        )
        controls_layout.addWidget(self.chk_include_formulae)

        # Applies to the WHOLE batch, not per-file -- deliberately simple
        # rather than prompting per-file, since the concrete case this
        # exists for (Income Tax AIS/TIS statements, bank statements) is
        # usually a batch of documents from the same source sharing one
        # password convention (e.g. PAN + DOB). A mixed-password batch isn't
        # supported; those files would need to be converted in separate runs.
        self.txt_pdf_password = QLineEdit()
        self.txt_pdf_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_pdf_password.setPlaceholderText("PDF password (if needed)")
        self.txt_pdf_password.setMaximumWidth(160)
        self.txt_pdf_password.setToolTip(
            "Applied to any password-protected PDF in this batch (e.g. \n"
            "Income Tax AIS/TIS statements). One password for the whole \n"
            "batch -- files needing a different password will fail with \n"
            "a clear error and need a separate run."
        )
        controls_layout.addWidget(self.txt_pdf_password)
        
        self.btn_clear = QPushButton("Clear Queue")
        self.btn_clear.clicked.connect(self.clear_queue)
        controls_layout.addWidget(self.btn_clear)

        self.btn_start = QPushButton("Start Conversion")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.setMinimumWidth(150)
        self.btn_start.clicked.connect(self.start_conversion)
        controls_layout.addWidget(self.btn_start)
        
        layout.addLayout(controls_layout)

    def apply_styles(self):
        self.setStyleSheet(LIGHT_STYLESHEET if self.theme == "light" else DARK_STYLESHEET)

    def update_analytics(self):
        process = psutil.Process(os.getpid())
        mem_mb = process.memory_info().rss / (1024 * 1024)
        self.lbl_memory.setText(f"RAM Usage: {mem_mb:.1f} MB")
        self.lbl_total_files.setText(f"Total Files: {self.table.rowCount()}")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file():
                self._add_file_if_supported(path)
            elif path.is_dir():
                self._process_folder(path)

    def add_files_dialog(self):
        # Build a filter string from supported extensions
        ext_list = ' '.join(f'*{ext}' for ext in sorted(SUPPORTED_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Files to Convert", "",
            f"Supported Files ({ext_list});;All Files (*.*)"
        )
        if files:
            added = 0
            skipped = 0
            for file_path in files:
                p = Path(file_path)
                if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                    self._add_file_to_table(p)
                    added += 1
                else:
                    skipped += 1
            if skipped > 0:
                QMessageBox.information(
                    self, "Files Added",
                    f"Added {added} supported file(s).\nSkipped {skipped} unsupported file(s)."
                )

    def add_folder_dialog(self):
        # QFileDialog.getExistingDirectory() uses the native Windows "Browse
        # For Folder" dialog by default, which never lists files -- that's a
        # Windows shell limitation, not something we can configure away while
        # using the native picker. Building the dialog manually with
        # DontUseNativeDialog + ShowDirsOnly(False) switches to Qt's own
        # directory dialog, which lists files alongside folders (grayed out,
        # not selectable) so you can see what's actually in a folder before
        # committing to it. Folder selection itself still works the normal
        # way: whichever subfolder is highlighted when you hit "Choose" gets
        # selected, or the currently open folder if nothing is highlighted.
        dialog = QFileDialog(self, "Select Folder to Convert")
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, False)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)

        if dialog.exec():
            selected = dialog.selectedFiles()
            if selected:
                self._process_folder(Path(selected[0]))

    def _process_folder(self, folder_path: Path):
        """Scan a folder, ask about subfolders, filter by supported types, and show summary."""
        # Ask about subfolders
        reply = QMessageBox.question(
            self, "Include Subfolders?",
            f"Selected folder:\n{folder_path}\n\nDo you want to include files from subfolders?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            all_files = [f for f in folder_path.rglob("*") if f.is_file()]
        else:
            all_files = [f for f in folder_path.glob("*") if f.is_file()]

        # Separate supported vs unsupported
        supported = [f for f in all_files if f.suffix.lower() in SUPPORTED_EXTENSIONS]
        skipped = len(all_files) - len(supported)

        if not supported:
            QMessageBox.warning(
                self, "No Supported Files",
                f"No supported files found in:\n{folder_path}\n\n"
                f"Total files scanned: {len(all_files)}\n"
                f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )
            return

        # Build a breakdown by type
        type_counts = Counter(f.suffix.lower() for f in supported)
        breakdown = ', '.join(f"{count} {ext.upper()}" for ext, count in sorted(type_counts.items()))

        # Confirmation dialog
        confirm = QMessageBox.question(
            self, "Confirm Add Files",
            f"Found {len(supported)} supported file(s):\n{breakdown}\n\n"
            f"Skipped {skipped} unsupported file(s).\n\n"
            f"Add these files to the conversion queue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if confirm == QMessageBox.StandardButton.Yes:
            for f in supported:
                self._add_file_to_table(f)

    def _add_file_if_supported(self, file_path: Path):
        """Add a single file only if its extension is supported."""
        if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            self._add_file_to_table(file_path)
        else:
            logger.debug(f"Skipped unsupported file: {file_path}")

    def _add_file_to_table(self, file_path: Path):
        # We can do a rudimentary extension check here, but router handles errors gracefully.
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        # Store full path in UserRole for the first item
        item_name = QTableWidgetItem(file_path.name)
        item_name.setData(Qt.ItemDataRole.UserRole, str(file_path))
        
        self.table.setItem(row, 0, item_name)
        self.table.setItem(row, 1, QTableWidgetItem(file_path.suffix.upper()))
        self.table.setItem(row, 2, QTableWidgetItem("Pending"))
        self.table.setItem(row, 3, QTableWidgetItem(""))

    def select_output_dir(self):
        start_dir = str(self.output_dir) if self.output_dir else str(Path.cwd())
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory", start_dir)
        if dir_path:
            self.output_dir = Path(dir_path)
            self.lbl_output_dir.setText(f"Output: {self.output_dir}")

    def clear_queue(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Warning", "Cannot clear queue while converting!")
            return
        self.table.setRowCount(0)
        self.progress_bar.setValue(0)
        self.lbl_processed.setText("Processed: 0")

    def start_conversion(self):
        if self.table.rowCount() == 0:
            return
            
        if self.worker and self.worker.isRunning():
            # Handle Cancel
            self.worker.cancel()
            self.btn_start.setText("Cancelling...")
            self.btn_start.setEnabled(False)
            return

        files_to_process = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 2).text() != "Done":
                file_path = Path(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))
                files_to_process.append(file_path)

        if not files_to_process:
            QMessageBox.information(self, "Info", "All files are already processed!")
            return

        self.btn_start.setText("Cancel Conversion")
        self.btn_start.setStyleSheet("background-color: #C53030;")
        
        self.worker = ConversionWorker(
            files_to_process,
            self.output_dir,
            include_images=self.chk_include_images.isChecked(),
            include_formulae=self.chk_include_formulae.isChecked(),
            pdf_password=self.txt_pdf_password.text(),
        )
        self.worker.progress_updated.connect(self.on_progress)
        self.worker.file_finished.connect(self.on_file_finished)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.batch_finished.connect(self.on_batch_finished)
        
        self.worker.start()
        
    def find_row_by_filepath(self, filepath: str) -> int:
        """Match rows by the full path stored in UserRole, not the display
        name. Two queued files can share the same filename if they came from
        different folders (a likely scenario given the "Add Folder +
        subfolders" workflow); matching on name alone would silently update
        the wrong row's status."""
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == filepath:
                return row
        return -1

    def on_progress(self, percent: int, file_key: str, status: str, output_path: str):
        self.progress_bar.setValue(percent)
        row = self.find_row_by_filepath(file_key)
        if row != -1:
            self.table.item(row, 2).setText(status)
            if output_path:
                self.table.setItem(row, 3, QTableWidgetItem(output_path))

    def on_file_finished(self, file_key: str, status: str, output_path: str):
        row = self.find_row_by_filepath(file_key)
        if row != -1:
            self.table.item(row, 2).setText(status)
            if output_path:
                self.table.setItem(row, 3, QTableWidgetItem(output_path))
                
        # Update Processed count safely
        current_processed = int(self.lbl_processed.text().split(":")[1].strip())
        self.lbl_processed.setText(f"Processed: {current_processed + 1}")

    def on_error(self, file_key: str, error_msg: str):
        row = self.find_row_by_filepath(file_key)
        if row != -1:
            self.table.item(row, 2).setText("Error")
            # We could show error_msg in output path column as a tooltip
            item = QTableWidgetItem("Failed")
            item.setToolTip(error_msg)
            self.table.setItem(row, 3, item)

    def on_batch_finished(self, success_count: int, fail_count: int):
        self.btn_start.setText("Start Conversion")
        self.btn_start.setEnabled(True)
        self.btn_start.setStyleSheet("") # Reset style
        self.apply_styles() # Re-apply base styles safely
        
        self.progress_bar.setValue(100)
        
        msg = f"Conversion finished!\nSuccess: {success_count}\nFailed: {fail_count}"
        QMessageBox.information(self, "Batch Complete", msg)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Ensure fonts look good across OS
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)
    
    window = MarkdownConverterApp()
    window.show()
    sys.exit(app.exec())
