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
    batch_finished = pyqtSignal(int, int, bool)  # success_count, fail_count, was_cancelled
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
        start_batch_time = time.perf_counter()
        success_count = 0
        fail_count = 0
        total_files = len(self.files_to_process)

        logger.info(f"=== BATCH CONVERSION STARTED: {total_files} file(s) in queue ===")

        if total_files == 0:
            self.batch_finished.emit(0, 0, False)
            return

        for i, file_path in enumerate(self.files_to_process, 1):
            if self.is_cancelled:
                logger.warning("Conversion cancelled by user before starting next file.")
                self.file_finished.emit(str(file_path), "Cancelled", "")
                break

            file_key = str(file_path)
            if self.output_dir:
                output_file = self.output_dir / f"{file_path.stem}.md"
            else:
                output_file = file_path.parent / f"{file_path.stem}.md"
            
            # Emit "Processing" status (0% into this file's own work)
            base_percent = int(((i - 1) / total_files) * 100)
            self.progress_updated.emit(base_percent, file_key, "Processing...", str(output_file))

            logger.info(f"--- Processing File [{i}/{total_files}]: '{file_path.name}' -> Target: '{output_file.name}' ---")

            def on_sub_progress(units_done: int, units_total: int, _i=i, _file_key=file_key):
                units_total = max(units_total, 1)
                file_fraction = units_done / units_total
                overall_percent = int((((_i - 1) + file_fraction) / total_files) * 100)

                if units_total > 1:
                    status = f"Processing... ({units_done}/{units_total} pages)"
                else:
                    status = "Processing..."

                self.progress_updated.emit(overall_percent, _file_key, status, "")

            try:
                if not file_path.exists():
                    raise FileNotFoundError(f"File not found on disk: {file_path}")
                
                self.router.process_file(
                    file_path,
                    output_file,
                    progress_callback=on_sub_progress,
                    include_images=self.include_images,
                    include_formulae=self.include_formulae,
                    pdf_password=self.pdf_password,
                    cancel_check=lambda: self.is_cancelled,
                )
                success_count += 1
                self.file_finished.emit(file_key, "Done", str(output_file))

            except InterruptedError:
                logger.warning(f"File [{i}/{total_files}] '{file_path.name}' CANCELLED by user.")
                self.file_finished.emit(file_key, "Cancelled", "")
                break
            except Exception as e:
                fail_count += 1
                logger.exception(f"File [{i}/{total_files}] failed: '{file_path.name}': {e}")
                self.error_occurred.emit(file_key, str(e))
                self.file_finished.emit(file_key, "Error", "")

        total_batch_elapsed = time.perf_counter() - start_batch_time
        if self.is_cancelled:
            logger.info(f"=== BATCH CONVERSION CANCELLED after {total_batch_elapsed:.2f}s (Success: {success_count}, Failed: {fail_count}) ===")
        else:
            logger.info(
                f"=== BATCH CONVERSION COMPLETED in {total_batch_elapsed:.2f}s ===\n"
                f"Success: {success_count}, Failed: {fail_count}, Total: {total_files}"
            )
            self.progress_updated.emit(100, "All done!", "Finished", "")
        
        self.batch_finished.emit(success_count, fail_count, self.is_cancelled)

    def cancel(self):
        """Sets the flag to break the loop safely and immediately."""
        logger.info("Cancel button clicked. Signalling worker thread to abort...")
        self.is_cancelled = True
