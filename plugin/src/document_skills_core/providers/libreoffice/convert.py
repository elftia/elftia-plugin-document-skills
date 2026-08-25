"""Office-to-PDF conversion via headless --convert-to pdf.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
import stat

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.temp_roots import OperationTempRoot
from .runner import LibreOfficeRunner

_DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024 * 1024


def convert_to_pdf(
    input_document: Path,
    runner: LibreOfficeRunner,
    *,
    max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
) -> bytes:
    """Convert DOCX/XLSX/PPTX to PDF via headless soffice.

    Returns the converted PDF bytes. The caller reopens and validates
    the output through the existing PDF validators before promotion.
    """
    with OperationTempRoot() as private_root:
        staged_input = private_root / ("input" + Path(input_document).suffix)
        staged_input.write_bytes(Path(input_document).read_bytes())
        staged_input.chmod(stat.S_IREAD)
        output_dir = private_root / "output"
        output_dir.mkdir()
        try:
            output = runner.convert(staged_input, "pdf", output_dir)
            output_bytes = output.stat().st_size
            if output_bytes > max_output_bytes:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "LibreOffice PDF output exceeds the requested byte ceiling.",
                    details={
                        "max_output_bytes": max_output_bytes,
                        "output_bytes": output_bytes,
                    },
                )
            return output.read_bytes()
        finally:
            staged_input.chmod(stat.S_IREAD | stat.S_IWRITE)
