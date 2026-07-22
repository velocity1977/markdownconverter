from pathlib import Path
from typing import List, Tuple, Optional
from PyQt6.QtCore import QThread, pyqtSignal
from router import SmartRouter
import time
import logging

logger = logging.getLogger(__name__)


class ConversionWorker(QThread):
    # Signals to communicate with the main GUI thread safely
    progress_updated = pyqtSignal(int, str, str, str)  # percentage, current_file_name, status, output_path
    file_finished = pyqtSignal(str, str, str) # current_file_name, status, output_path
    batch_finished = pyqtSignal(int, int)  # success_count, fail_count
    error_occurred = pyqtSignal(str, str) # current_file_name, error_message

    def __init__(self, files_to_process: List[Path], output_dir: Optional[Path], include_images: bool = False, include_formulae: bool = False, pdf_password: str = ""):
        super().__init__()
        self.files_to_process = files_to_process
        self.output_dir = output_dir
        self.include_images = include_images
        self.include_formulae = include_formulae
        self.pdf_password = pdf_password
        self.router = SmartRouter()
        self.is_cancelled = False

    def run(self):
        success_count = 0
        fail_count = 0
        total_files = len(self.files_to_process)

        if total_files == 0:
            self.batch_finished.emit(0, 0)
            return

        for i, file_path in enumerate(self.files_to_process):
            if self.is_cancelled:
                break

            # Use the FULL resolved path (not just file_path.name) as the key
            # for all signals. Two queued files can share the same filename if
            # they came from different folders (very likely given the "Add
            # Folder + subfolders" feature), and the UI previously matched rows
            # by display name alone, which would update the wrong row's status
            # whenever names collided. The full path is unique per row.
            file_key = str(file_path)
            if self.output_dir:
                output_file = self.output_dir / f"{file_path.stem}.md"
            else:
                output_file = file_path.parent / f"{file_path.stem}.md"
            
            # Emit "Processing" status (0% into this file's own work)
            base_percent = int((i / total_files) * 100)
            self.progress_updated.emit(base_percent, file_key, "Processing...", str(output_file))

            def on_sub_progress(units_done: int, units_total: int, _i=i, _file_key=file_key):
                """
                Turns a converter's internal progress (e.g. "page 45 of 1004")
                into an overall queue percentage, so a single large PDF moves
                the bar continuously instead of sitting frozen at one number
                for however long that file takes. `_i`/`_file_key` are bound
                as default args to capture this loop iteration's values --
                without that, every callback created in this loop would share
                the *final* values of `i`/`file_key` once the loop moved on,
                since closures capture variables, not their values at
                creation time.
                """
                units_total = max(units_total, 1)  # avoid divide-by-zero
                file_fraction = units_done / units_total
                overall_percent = int(((_i + file_fraction) / total_files) * 100)

                if units_total > 1:
                    status = f"Processing... ({units_done}/{units_total} pages)"
                else:
                    status = "Processing..."

                self.progress_updated.emit(overall_percent, _file_key, status, "")

            try:
                # Typecheck & existence
                if not file_path.exists():
                    raise FileNotFoundError("File not found on disk.")
                
                # Convert. router.process_file() only ever returns True or
                # raises -- BaseConverter.convert()'s contract (see
                # converters.py) is "return True on success, raise on
                # failure," and every converter follows it. So there's no
                # code path where `success` comes back falsy; the old
                # if/else here had a dead "Failed" branch that could never
                # run. Failures are reported through the except clause below.
                self.router.process_file(
                    file_path,
                    output_file,
                    progress_callback=on_sub_progress,
                    include_images=self.include_images,
                    include_formulae=self.include_formulae,
                    pdf_password=self.pdf_password,
                )
                success_count += 1
                self.file_finished.emit(file_key, "Done", str(output_file))

            except Exception as e:
                fail_count += 1
                self.error_occurred.emit(file_key, str(e))
                self.file_finished.emit(file_key, "Error", "")

            # Small yield to prevent CPU hogging in the background thread
            time.sleep(0.05)

        # Final progress update
        if not self.is_cancelled:
            self.progress_updated.emit(100, "All done!", "Finished", "")
        
        self.batch_finished.emit(success_count, fail_count)

    def cancel(self):
        """Sets the flag to break the loop safely."""
        self.is_cancelled = True
