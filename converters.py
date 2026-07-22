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
    ) -> bool:
        """
        Converts the input file to markdown and saves it to output_path.
        Returns True if successful, raises an Exception otherwise.

        progress_callback, if given, is called as callback(units_done,
        units_total) as work proceeds -- e.g. (pages_done, total_pages) for
        the PDF converter. Converters that can't report sub-file progress
        (MarkItDown's single blocking call) should still call it with (0, 1)
        before starting and (1, 1) once done, so callers can treat every file
        uniformly as "some number of units out of a total."

        include_images: if True, embed figures/diagrams found in the source
        file inline in the output markdown (as a sibling '<stem>_assets/'
        folder of PNGs, referenced via standard markdown image syntax).
        Converters that have no such capability (MarkItDown, currently) just
        ignore this flag.

        include_formulae: if True, repair math/Greek symbols that were
        garbled by Adobe-Symbol-font Private-Use-Area encoding (see
        symbol_fonts.py) -- e.g. angle signs, Greek letters, sqrt, relations.
        This is a plain-Unicode fix, not LaTeX reconstruction: layout of
        multi-line fractions/stacked expressions is a separate, much larger
        problem this does not attempt to solve.

        pdf_password: applied to password-protected PDFs (e.g. Income Tax
        AIS/TIS statements, bank statements) -- one password for the whole
        batch, not per-file. Converters that can't be password-protected
        (MarkItDown's formats, currently) just ignore this.
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
    ) -> bool:
        """Converts Office/Web files using Microsoft's MarkItDown."""
        # include_formulae and pdf_password are accepted for interface
        # consistency with BaseConverter but not used here: neither the
        # Symbol-font fix nor password-protection currently apply to
        # MarkItDown's formats. (Word/Excel/PowerPoint files CAN be
        # password-protected too, but MarkItDown has no decrypt path today
        # -- that's a separate, not-yet-handled gap, not something this
        # parameter quietly ignores by mistake.)
        #
        # include_images IS handled here, via office_images.py -- MarkItDown
        # itself doesn't actually embed or extract images for docx/pptx (see
        # that module's docstring for exactly what's broken and why), so we
        # extract the real image bytes ourselves from the underlying OOXML
        # zip structure and splice them into MarkItDown's output afterward.
        # Typecheck & OS Protection
        if not input_path.exists() or not input_path.is_file():
            logger.error(f"File not found: {input_path}")
            raise FileNotFoundError(f"Input file not found or is not a file: {input_path}")
            
        try:
            logger.debug(f"MarkItDown converting: {input_path}")
            # MarkItDown's convert() is a single blocking call with no
            # internal progress hooks -- there's no page/chunk loop to report
            # from. We still call the callback at the start and end so the
            # caller can treat this file as "1 unit" just like a PDF's pages,
            # instead of needing a special case per converter type.
            if progress_callback:
                progress_callback(0, 1)

            result = self.md.convert(str(input_path))
            text_content = result.text_content

            if include_images:
                suffix = input_path.suffix.lower()
                assets_relative_dir = f"{output_path.stem}_assets"
                assets_abs_dir = output_path.parent / assets_relative_dir
                try:
                    if suffix == ".docx":
                        images = extract_docx_images_in_order(input_path)
                        text_content = replace_images_in_order(
                            text_content, DOCX_IMAGE_PLACEHOLDER_RE, images,
                            assets_abs_dir, assets_relative_dir,
                        )
                    elif suffix == ".pptx":
                        images = extract_pptx_images_in_order(input_path)
                        text_content = replace_images_in_order(
                            text_content, PPTX_IMAGE_PLACEHOLDER_RE, images,
                            assets_abs_dir, assets_relative_dir,
                        )
                    # .xlsx and other formats: no embedded-image extraction
                    # implemented (MarkItDown doesn't surface any placeholder
                    # to substitute for those today either).
                except Exception:
                    # Image extraction failing should never take down the
                    # whole conversion -- fall back to MarkItDown's original
                    # (non-functional-but-harmless) placeholder output.
                    logger.exception(
                        f"Image extraction failed for {input_path}; "
                        f"keeping MarkItDown's original output for this file."
                    )
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text_content)

            if progress_callback:
                progress_callback(1, 1)
            
            logger.debug(f"MarkItDown success: {output_path}")
            return True
        except Exception as e:
            logger.exception(f"MarkItDown Error on {input_path}: {str(e)}")
            raise RuntimeError(f"MarkItDown conversion failed for {input_path}: {str(e)}")
        finally:
            # Force cleanup
            gc.collect()


class PyMuPDFConverter(BaseConverter):
    """Converter for PDF files using PyMuPDF4LLM with strict chunking for memory safety."""

    def __init__(self, chunk_size: int = 15):
        self.chunk_size = chunk_size

    def convert(
        self,
        input_path: Path,
        output_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        include_images: bool = False,
        include_formulae: bool = False,
        pdf_password: str = "",
    ) -> bool:
        """Converts PDFs to Markdown using pagination chunking."""
        # Typecheck & OS Protection
        if not input_path.exists() or not input_path.is_file():
            logger.error(f"PDF not found: {input_path}")
            raise FileNotFoundError(f"Input file not found or is not a file: {input_path}")
            
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()

        try:
            logger.debug(f"Opening PDF for chunking: {input_path}")
            doc = pymupdf.open(str(input_path))

            # Password-protected PDFs (Income Tax AIS/TIS statements, bank
            # statements, etc. are commonly protected this way) open fine at
            # this point -- PyMuPDF can read the XREF/page count without
            # authenticating -- but fail deep inside pymupdf4llm's own
            # IdentifyHeaders() the moment it tries to actually load a page's
            # content, with a generic "document closed or encrypted"
            # ValueError that gives no indication a password is the issue.
            # Checking doc.needs_pass up front lets us fail with a message
            # that actually tells the user what happened and what to do.
            if doc.needs_pass:
                if not pdf_password:
                    raise RuntimeError(
                        "This PDF is password-protected. Enter the password "
                        "in the \"PDF Password\" field and try converting again."
                    )
                # doc.authenticate() returns 0 on failure, nonzero on success
                # (it's not a plain bool despite reading like one).
                if not doc.authenticate(pdf_password):
                    raise RuntimeError(
                        "This PDF is password-protected, and the password "
                        "entered didn't unlock it. Double-check the password "
                        "and try again."
                    )

            total_pages = len(doc)
            logger.debug(f"Total pages to process: {total_pages}")

            # IMPORTANT: compute header-detection info ONCE for the whole
            # document. If `hdr_info` is left unset, pymupdf4llm.to_markdown()
            # builds it internally via IdentifyHeaders(doc), which scans every
            # page of the *entire* doc to work out font-size -> heading level.
            # Since that scan ignores the `pages` filter, leaving it unset here
            # meant we were re-scanning all `total_pages` pages once per chunk
            # (~total_pages/chunk_size times) just to discard everything but a
            # 1004-page book, that's ~67x more text-extraction work than
            # necessary, and it's the main reason large PDFs were slow. It also
            # risks inconsistent heading levels between chunks in principle.
            hdr_info = pymupdf4llm.IdentifyHeaders(doc)

            # --- Image/diagram embedding setup ---
            # pymupdf4llm's write_images writes files to `image_path` AND
            # embeds that exact string as the markdown link target. If we
            # pass an absolute path, the .md ends up with an absolute link
            # that breaks the moment the folder is copied elsewhere or opened
            # on another machine. So we pass the ABSOLUTE path in for the
            # actual disk write (guarantees it lands in the right place
            # regardless of process working directory), then rewrite that
            # exact prefix to a clean relative one before the text ever
            # touches disk. The assets folder sits next to the output .md,
            # named after it, so moving "<name>.md" + "<name>_assets/"
            # together as a pair keeps every link intact.
            images_relative_dir = f"{output_path.stem}_assets"
            images_abs_dir = output_path.parent / images_relative_dir
            if include_images:
                images_abs_dir.mkdir(parents=True, exist_ok=True)
            images_abs_prefix = str(images_abs_dir).replace("\\", "/")

            for start_page in range(0, total_pages, self.chunk_size):
                end_page = min(start_page + self.chunk_size - 1, total_pages - 1)
                logger.debug(f"Processing pages {start_page} to {end_page}")
                
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
                    # Fixes Adobe-Symbol-font PUA garbling (angle signs,
                    # Greek letters, sqrt, relations) -- see symbol_fonts.py
                    # for why this is a reliable, table-driven fix rather
                    # than a guess. Cheap: a single regex pass per chunk.
                    md_text = remap_symbol_chars(md_text)
                
                with open(output_path, 'a', encoding='utf-8') as f:
                    f.write(md_text)
                    f.write("\n\n")
                
                del md_text
                gc.collect()
                time.sleep(0.01)

                # Report real sub-file progress after each chunk so a single
                # large PDF doesn't leave the UI's progress bar sitting frozen
                # for however long the whole file takes.
                if progress_callback:
                    progress_callback(end_page + 1, total_pages)
                
            doc.close()
            logger.debug(f"PyMuPDF success: {output_path}")
            return True
            
        except Exception as e:
            logger.exception(f"PyMuPDF Error on {input_path}: {str(e)}")
            raise RuntimeError(f"PyMuPDF conversion failed for {input_path}: {str(e)}")
        finally:
            # Final rigid cleanup
            gc.collect()
