import gc
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, List, Callable
import logging

import pymupdf4llm
import pymupdf  # Ensure fitz is accessible via pymupdf
from markitdown import MarkItDown

from symbol_fonts import remap_symbol_chars
from office_images import (
    extract_docx_images_in_order,
    extract_pptx_images_in_order,
    replace_images_in_order,
    DOCX_IMAGE_PLACEHOLDER_RE,
    PPTX_IMAGE_PLACEHOLDER_RE,
)

logger = logging.getLogger(__name__)

# --- Upstream bug workaround (pymupdf4llm==0.0.11) ---
# pymupdf4llm.helpers.pymupdf_rag defines a module-level `bullet` variable as a
# *list* of bullet-point characters, then calls span0["text"].startswith(bullet)
# inside write_text(). str.startswith() only accepts a str or a tuple of str,
# so this raises: "TypeError: startswith first arg must be str or a tuple of
# str, not list" on the very first line of body text that happens to look like
# a bullet/list item (i.e. almost any real-world PDF). Patch it to a tuple
# once, here, before any conversion runs.
try:
    from pymupdf4llm.helpers import pymupdf_rag as _pymupdf_rag
    if isinstance(_pymupdf_rag.bullet, list):
        _pymupdf_rag.bullet = tuple(_pymupdf_rag.bullet)
        logger.debug("Patched pymupdf4llm.helpers.pymupdf_rag.bullet list -> tuple")
except Exception:
    logger.exception("Failed to patch pymupdf4llm bullet bug; PDF conversion may fail")

class BaseConverter(ABC):
    """Abstract base class for all document converters."""

    @abstractmethod
    def convert(
        self,
        input_path: Path,
        output_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        include_images: bool = False,
        include_formulae: bool = False,
        pdf_password: str = "",
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        Converts the input file to markdown and saves it to output_path.
        Returns True if successful, raises an Exception otherwise.

        progress_callback, if given, is called as callback(units_done,
        units_total) as work proceeds -- e.g. (pages_done, total_pages) for
        the PDF converter.

        cancel_check, if given, is a callable returning True if the conversion
        has been cancelled by the user. If True, the converter immediately aborts
        work and raises InterruptedError.
        """
        pass


class MarkItDownConverter(BaseConverter):
    """Converter for MS Office files and general documents using MarkItDown."""

    def __init__(self):
        self.md = MarkItDown()

    def convert(
        self,
        input_path: Path,
        output_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        include_images: bool = False,
        include_formulae: bool = False,
        pdf_password: str = "",
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Converts Office/Web files using Microsoft's MarkItDown."""
        if not input_path.exists() or not input_path.is_file():
            logger.error(f"File not found: {input_path}")
            raise FileNotFoundError(f"Input file not found or is not a file: {input_path}")
            
        if cancel_check and cancel_check():
            raise InterruptedError("Conversion cancelled by user.")

        try:
            start_time = time.perf_counter()
            file_size_mb = input_path.stat().st_size / (1024 * 1024)
            logger.info(
                f"[Tool: Microsoft MarkItDown] Starting conversion for '{input_path.name}' "
                f"(Size: {file_size_mb:.2f} MB, Format: {input_path.suffix.upper()})"
            )

            if progress_callback:
                progress_callback(0, 1)

            result = self.md.convert(str(input_path))
            text_content = result.text_content

            if cancel_check and cancel_check():
                raise InterruptedError("Conversion cancelled by user.")

            if include_images:
                suffix = input_path.suffix.lower()
                assets_relative_dir = f"{output_path.stem}_assets"
                assets_abs_dir = output_path.parent / assets_relative_dir
                try:
                    if suffix == ".docx":
                        logger.info(f"[Tool: Microsoft MarkItDown + OOXML Extractor] Extracting images for '{input_path.name}'")
                        images = extract_docx_images_in_order(input_path)
                        text_content = replace_images_in_order(
                            text_content, DOCX_IMAGE_PLACEHOLDER_RE, images,
                            assets_abs_dir, assets_relative_dir,
                        )
                        logger.info(f"[Tool: Microsoft MarkItDown + OOXML Extractor] Extracted {len(images)} images to '{assets_relative_dir}'")
                    elif suffix == ".pptx":
                        logger.info(f"[Tool: Microsoft MarkItDown + OOXML Extractor] Extracting slides/images for '{input_path.name}'")
                        images = extract_pptx_images_in_order(input_path)
                        text_content = replace_images_in_order(
                            text_content, PPTX_IMAGE_PLACEHOLDER_RE, images,
                            assets_abs_dir, assets_relative_dir,
                        )
                        logger.info(f"[Tool: Microsoft MarkItDown + OOXML Extractor] Extracted {len(images)} images to '{assets_relative_dir}'")
                except Exception:
                    logger.exception(
                        f"[Tool: Microsoft MarkItDown] Image extraction failed for {input_path}; "
                        f"keeping MarkItDown's original output for this file."
                    )
            
            if cancel_check and cancel_check():
                raise InterruptedError("Conversion cancelled by user.")

            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text_content)

            if progress_callback:
                progress_callback(1, 1)
            
            elapsed = time.perf_counter() - start_time
            out_size_kb = output_path.stat().st_size / 1024
            logger.info(
                f"[Tool: Microsoft MarkItDown] SUCCESS: Converted '{input_path.name}' -> '{output_path.name}' "
                f"in {elapsed:.2f}s (Output: {out_size_kb:.1f} KB)"
            )
            return True
        except InterruptedError:
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass
            raise
        except Exception as e:
            logger.exception(f"[Tool: Microsoft MarkItDown] FAILED on {input_path}: {str(e)}")
            raise RuntimeError(f"MarkItDown conversion failed for {input_path}: {str(e)}")
        finally:
            # Force cleanup
            gc.collect()


class PyMuPDFConverter(BaseConverter):
    """Converter for PDF files using PyMuPDF4LLM with strict chunking for memory safety."""

    def __init__(self, chunk_size: int = 50):
        self.chunk_size = chunk_size

    def convert(
        self,
        input_path: Path,
        output_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        include_images: bool = False,
        include_formulae: bool = False,
        pdf_password: str = "",
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Converts PDFs to Markdown using pagination chunking."""
        # Typecheck & OS Protection
        if not input_path.exists() or not input_path.is_file():
            logger.error(f"[Tool: PyMuPDF4LLM] PDF not found: {input_path}")
            raise FileNotFoundError(f"Input file not found or is not a file: {input_path}")
            
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            try:
                output_path.unlink()
            except Exception:
                pass

        doc = None
        start_time = time.perf_counter()
        try:
            file_size_mb = input_path.stat().st_size / (1024 * 1024)
            logger.info(
                f"[Tool: PyMuPDF4LLM (PyMuPDF)] Opening PDF '{input_path.name}' "
                f"(Size: {file_size_mb:.2f} MB, Chunk size: {self.chunk_size} pages)"
            )
            doc = pymupdf.open(str(input_path))

            if doc.needs_pass:
                if not pdf_password:
                    raise RuntimeError(
                        "This PDF is password-protected. Enter the password "
                        "in the \"PDF Password\" field and try converting again."
                    )
                if not doc.authenticate(pdf_password):
                    raise RuntimeError(
                        "This PDF is password-protected, and the password "
                        "entered didn't unlock it. Double-check the password "
                        "and try again."
                    )
                logger.info(f"[Tool: PyMuPDF4LLM] Successfully authenticated encrypted PDF '{input_path.name}'")

            total_pages = len(doc)
            logger.info(f"[Tool: PyMuPDF4LLM] Total pages to process: {total_pages}")

            # Compute header hierarchy once
            hdr_start = time.perf_counter()
            hdr_info = pymupdf4llm.IdentifyHeaders(doc)
            hdr_elapsed = time.perf_counter() - hdr_start
            logger.debug(f"[Tool: PyMuPDF4LLM] Header analysis completed in {hdr_elapsed:.2f}s")

            images_relative_dir = f"{output_path.stem}_assets"
            images_abs_dir = output_path.parent / images_relative_dir
            if include_images:
                images_abs_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"[Tool: PyMuPDF4LLM] Image extraction enabled. Output folder: '{images_relative_dir}'")
            images_abs_prefix = str(images_abs_dir).replace("\\", "/")

            total_chunks = (total_pages + self.chunk_size - 1) // self.chunk_size
            for chunk_idx, start_page in enumerate(range(0, total_pages, self.chunk_size), 1):
                # IMMEDIATE cancellation check before each chunk
                if cancel_check and cancel_check():
                    logger.warning(f"[Tool: PyMuPDF4LLM] Conversion CANCELLED by user at chunk {chunk_idx}/{total_chunks} (page {start_page + 1}/{total_pages})")
                    if output_path.exists():
                        try:
                            output_path.unlink()
                        except Exception:
                            pass
                    raise InterruptedError("Conversion cancelled by user.")

                end_page = min(start_page + self.chunk_size - 1, total_pages - 1)
                chunk_page_count = end_page - start_page + 1
                chunk_start = time.perf_counter()
                
                md_text = pymupdf4llm.to_markdown(
                    doc=doc,
                    pages=list(range(start_page, end_page + 1)),
                    hdr_info=hdr_info,
                    write_images=include_images,
                    image_path=images_abs_prefix,
                    page_chunks=False
                )

                if include_images:
                    md_text = md_text.replace(images_abs_prefix, images_relative_dir)

                if include_formulae:
                    md_text = remap_symbol_chars(md_text)
                
                with open(output_path, 'a', encoding='utf-8') as f:
                    f.write(md_text)
                    f.write("\n\n")
                
                del md_text
                gc.collect()

                chunk_elapsed = time.perf_counter() - chunk_start
                pages_per_sec = chunk_page_count / max(chunk_elapsed, 0.001)
                logger.info(
                    f"[Tool: PyMuPDF4LLM] Chunk {chunk_idx}/{total_chunks} "
                    f"(Pages {start_page + 1}-{end_page + 1} of {total_pages}) converted in {chunk_elapsed:.2f}s "
                    f"({pages_per_sec:.1f} pages/sec)"
                )

                if progress_callback:
                    progress_callback(end_page + 1, total_pages)
                
            doc.close()
            doc = None
            total_elapsed = time.perf_counter() - start_time
            avg_speed = total_pages / max(total_elapsed, 0.001)
            out_size_kb = output_path.stat().st_size / 1024
            logger.info(
                f"[Tool: PyMuPDF4LLM] SUCCESS: Converted '{input_path.name}' ({total_pages} pages) -> '{output_path.name}' "
                f"in {total_elapsed:.2f}s (Avg Speed: {avg_speed:.1f} pages/sec, Output: {out_size_kb:.1f} KB)"
            )
            return True
        except InterruptedError:
            if doc and not doc.is_closed:
                doc.close()
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass
            raise
        except Exception as e:
            logger.exception(f"[Tool: PyMuPDF4LLM] FAILED on {input_path}: {str(e)}")
            raise RuntimeError(f"PyMuPDF conversion failed for {input_path}: {str(e)}")
        finally:
            if doc and not doc.is_closed:
                doc.close()
            gc.collect()
