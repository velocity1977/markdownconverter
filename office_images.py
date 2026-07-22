"""
Real image extraction for Office documents (.docx / .pptx), to fix a real gap
in MarkItDown: it doesn't actually embed or extract images for these formats.

WHAT MARKITDOWN ACTUALLY DOES TODAY (verified directly, not assumed)
---------------------------------------------------------------------
- .docx: emits a fixed, literal placeholder string for every image --
  `![](data:image/png;base64...)` -- note the trailing "..." is NOT a
  truncated real base64 payload, it is exactly that text every single time,
  regardless of what the image actually is. Non-functional.
- .pptx: emits `![originalname](PictureN.ext)`, but never actually saves
  `PictureN.ext` anywhere -- it's a dangling reference to a file that was
  never created. Non-functional.
- .xlsx: doesn't attempt to handle embedded images at all (silently skipped,
  not handled by this module).

THE FIX
-------
Both .docx and .pptx are OOXML, which means they're ZIP archives with a
standard, well-documented internal structure: real image bytes live in
word/media/ or ppt/media/, and the document's true reading order is
recoverable by walking the relevant XML (document.xml for docx, each
slideN.xml for pptx) and resolving each <a:blip r:embed="rIdN"/> reference
through the matching _rels/*.rels relationship file. This module does that
directly -- no new pip dependency, just the standard library's zipfile and
xml.etree.

SAFETY: POSITIONAL SUBSTITUTION IS ONLY EVER DONE WHEN COUNTS MATCH
---------------------------------------------------------------------
MarkItDown's placeholders are assumed to appear in the same order as the
images we independently extract from the XML, so replacing the Nth
placeholder with the Nth extracted image is normally correct. But if the
placeholder count and extracted-image count ever disagree (e.g. an image
format MarkItDown's HTML path doesn't recognize but the XML relationship
still lists, or vice versa), silently doing positional substitution risks
showing the WRONG image next to the wrong text -- confidently wrong is worse
than visibly broken. In that case this module does NOT guess: it strips the
non-functional placeholders and appends every successfully extracted image
in a clearly labeled section at the end instead, so nothing is lost, but
nothing is potentially mislabeled either.
"""

import logging
import posixpath
import re
import zipfile
from pathlib import Path
from typing import List, Tuple
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

_A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}

# MarkItDown's docx placeholder is a fixed literal string in current
# versions, but matching the general data-URI shape (rather than the exact
# string) is more robust to minor wording/mime-type variations across
# MarkItDown releases.
DOCX_IMAGE_PLACEHOLDER_RE = re.compile(r"!\[[^\]]*\]\(data:image/[^)]*\)")

# MarkItDown's pptx placeholder always follows the "PictureN.ext" naming
# pattern for the (nonexistent) target file.
PPTX_IMAGE_PLACEHOLDER_RE = re.compile(r"!\[[^\]]*\]\(Picture\d+\.[a-zA-Z0-9]+\)")


def extract_docx_images_in_order(docx_path: Path) -> List[Tuple[str, bytes]]:
    """Returns [(extension, image_bytes), ...] in true document reading order."""
    try:
        with zipfile.ZipFile(docx_path) as z:
            rels_root = ET.fromstring(z.read("word/_rels/document.xml.rels"))
            rid_to_target = {
                rel.get("Id"): rel.get("Target")
                for rel in rels_root.findall("r:Relationship", _REL_NS)
                if "image" in (rel.get("Type") or "")
            }

            doc_root = ET.fromstring(z.read("word/document.xml"))
            ordered_rids = [
                blip.get(f"{_R_NS}embed")
                for blip in doc_root.iter(f"{_A_NS}blip")
                if blip.get(f"{_R_NS}embed")
            ]

            images = []
            for rid in ordered_rids:
                target = rid_to_target.get(rid)
                if not target:
                    continue
                zip_path = posixpath.normpath("word/" + target)
                try:
                    data = z.read(zip_path)
                except KeyError:
                    logger.debug(f"docx image relationship pointed at missing entry: {zip_path}")
                    continue
                images.append((target.rsplit(".", 1)[-1].lower(), data))
            return images
    except (KeyError, ET.ParseError, zipfile.BadZipFile):
        logger.debug(f"Could not extract images from {docx_path}", exc_info=True)
        return []


def extract_pptx_images_in_order(pptx_path: Path) -> List[Tuple[str, bytes]]:
    """Returns [(extension, image_bytes), ...] in slide order, then in-slide order."""
    try:
        with zipfile.ZipFile(pptx_path) as z:
            slide_names = [n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]

            def _slide_num(name: str) -> int:
                # Sorted numerically, not alphabetically -- "slide10.xml"
                # must not sort before "slide2.xml".
                match = re.search(r"slide(\d+)\.xml$", name)
                return int(match.group(1)) if match else 0

            slide_names.sort(key=_slide_num)

            images = []
            for slide_name in slide_names:
                rels_name = f"ppt/slides/_rels/{slide_name.split('/')[-1]}.rels"
                rid_to_target = {}
                if rels_name in z.namelist():
                    rels_root = ET.fromstring(z.read(rels_name))
                    rid_to_target = {
                        rel.get("Id"): rel.get("Target")
                        for rel in rels_root.findall("r:Relationship", _REL_NS)
                        if "image" in (rel.get("Type") or "")
                    }

                slide_root = ET.fromstring(z.read(slide_name))
                for blip in slide_root.iter(f"{_A_NS}blip"):
                    embed = blip.get(f"{_R_NS}embed")
                    if not embed or embed not in rid_to_target:
                        continue
                    target = rid_to_target[embed]
                    zip_path = posixpath.normpath("ppt/slides/" + target)
                    try:
                        data = z.read(zip_path)
                    except KeyError:
                        logger.debug(f"pptx image relationship pointed at missing entry: {zip_path}")
                        continue
                    images.append((target.rsplit(".", 1)[-1].lower(), data))
            return images
    except (KeyError, ET.ParseError, zipfile.BadZipFile):
        logger.debug(f"Could not extract images from {pptx_path}", exc_info=True)
        return []


def replace_images_in_order(
    md_text: str,
    placeholder_pattern: "re.Pattern",
    images: List[Tuple[str, bytes]],
    assets_dir: Path,
    assets_relative_name: str,
) -> str:
    """
    Replaces each occurrence of `placeholder_pattern` in `md_text`, in order,
    with a real markdown image reference to a file written into `assets_dir`
    (named `assets_relative_name` in the emitted relative link, matching the
    PDF converter's "<stem>_assets/" convention). Falls back to a labeled
    end-of-document section (no positional guessing) if the placeholder
    count and image count don't match -- see module docstring for why.
    """
    matches = list(placeholder_pattern.finditer(md_text))

    if not images:
        # Nothing to substitute; leave text as-is (still non-functional
        # placeholders if MarkItDown produced any, but nothing broke).
        return md_text

    if len(matches) != len(images):
        logger.debug(
            f"Placeholder count ({len(matches)}) != extracted image count "
            f"({len(images)}); falling back to an appended image section "
            f"instead of risking a wrong positional match."
        )
        cleaned = placeholder_pattern.sub("", md_text)
        assets_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "\n\n---\n\n## Extracted Images\n",
            "_Automatic inline positioning wasn't possible for this file "
            "(the number of image placeholders didn't match the number of "
            "images found in the file); images are listed here instead._\n",
        ]
        for i, (ext, data) in enumerate(images):
            fname = f"image_{i + 1}.{ext}"
            (assets_dir / fname).write_bytes(data)
            lines.append(f"![]({assets_relative_name}/{fname})\n")
        return cleaned + "\n".join(lines)

    assets_dir.mkdir(parents=True, exist_ok=True)
    result_parts = []
    last_end = 0
    for i, match in enumerate(matches):
        ext, data = images[i]
        fname = f"image_{i + 1}.{ext}"
        (assets_dir / fname).write_bytes(data)
        result_parts.append(md_text[last_end:match.start()])
        result_parts.append(f"![]({assets_relative_name}/{fname})")
        last_end = match.end()
    result_parts.append(md_text[last_end:])
    return "".join(result_parts)
