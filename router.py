from pathlib import Path
from typing import Optional, Callable
from converters import BaseConverter, MarkItDownConverter, PyMuPDFConverter

SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.xlsx', '.pptx', '.html', '.csv', '.json', '.xml', '.txt'}

class SmartRouter:
    """
    Intelligently routes files to the appropriate converter based on extension or MIME type.
    """
    
    def __init__(self):
        # Initialize the converters once to reuse them
        self.markitdown_converter = MarkItDownConverter()
        self.pdf_converter = PyMuPDFConverter(chunk_size=15)
        
        # Mapping of extensions to their respective converter
        self.extension_map = {
            # PDF
            '.pdf': self.pdf_converter,
            
            # MS Office & Text (handled by MarkItDown)
            '.docx': self.markitdown_converter,
            '.xlsx': self.markitdown_converter,
            '.pptx': self.markitdown_converter,
            '.html': self.markitdown_converter,
            '.csv': self.markitdown_converter,
            '.json': self.markitdown_converter,
            '.xml': self.markitdown_converter,
            '.txt': self.markitdown_converter,
        }

    def get_converter(self, file_path: Path) -> Optional[BaseConverter]:
        """
        Returns the appropriate converter for the given file, or None if unsupported.
        """
        ext = file_path.suffix.lower()
        return self.extension_map.get(ext)

    def is_supported(self, file_path: Path) -> bool:
        """Check if a file format is supported."""
        return file_path.suffix.lower() in self.extension_map

    def process_file(
        self,
        input_path: Path,
        output_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        include_images: bool = False,
        include_formulae: bool = False,
        pdf_password: str = "",
    ) -> bool:
        """
        Determine the converter and process the file.
        Returns True if successful, raises Exceptions on failure.
        """
        converter = self.get_converter(input_path)
        if not converter:
            raise ValueError(f"Unsupported file format: {input_path.suffix}")
            
        return converter.convert(
            input_path,
            output_path,
            progress_callback=progress_callback,
            include_images=include_images,
            include_formulae=include_formulae,
            pdf_password=pdf_password,
        )
