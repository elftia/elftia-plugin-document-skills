"""Office-to-PDF conversion via headless --convert-to pdf.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path

from ...core.io.temp_roots import OperationTempRoot
from .constants import TIMEOUT_CONVERT
from .input_snapshot import private_libreoffice_input
from .output import read_provider_output
from .runner import LibreOfficeRunner


def convert_to_pdf(
    input_document: Path,
    runner: LibreOfficeRunner,
    *,
    max_output_bytes: int | None = None,
) -> bytes:
    """Convert DOCX/XLSX/PPTX to PDF via headless soffice.

    Returns the converted PDF bytes. The caller reopens and validates
    the output through the existing PDF validators before promotion.
    """
    with private_libreoffice_input(
        input_document,
        operation="libreoffice.convert-pdf",
    ) as snapshot:
        return convert_snapshot_to_pdf(
            snapshot.path,
            runner,
            max_output_bytes=max_output_bytes,
        )


def convert_snapshot_to_pdf(
    input_snapshot: Path,
    runner: LibreOfficeRunner,
    *,
    max_output_bytes: int | None = None,
) -> bytes:
    """Convert an already screened private snapshot without copying it again."""

    with OperationTempRoot() as private_root:
        output_dir = private_root / "output"
        output_dir.mkdir()
        output = runner.convert(
            input_snapshot,
            "pdf",
            output_dir,
            timeout_seconds=TIMEOUT_CONVERT,
        )
        return read_provider_output(
            output,
            "pdf",
            max_output_bytes=max_output_bytes,
        )
