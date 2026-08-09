"""Office-to-PDF conversion via headless --convert-to pdf.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path

from ...core.io.temp_roots import OperationTempRoot
from .runner import LibreOfficeRunner


def convert_to_pdf(
    input_document: Path,
    runner: LibreOfficeRunner,
) -> bytes:
    """Convert DOCX/XLSX/PPTX to PDF via headless soffice.

    Returns the converted PDF bytes. The caller reopens and validates
    the output through the existing PDF validators before promotion.
    """
    with OperationTempRoot() as private_root:
        staged_input = private_root / ("input" + Path(input_document).suffix)
        staged_input.write_bytes(Path(input_document).read_bytes())
        output_dir = private_root / "output"
        output_dir.mkdir()
        output = runner.convert(staged_input, "pdf", output_dir)
        return output.read_bytes()
