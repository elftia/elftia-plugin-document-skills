"""Legacy ``.doc``/``.xls``/``.ppt`` read/convert via headless soffice.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
import stat

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.temp_roots import OperationTempRoot
from .runner import LibreOfficeRunner

_LEGACY_TARGETS: dict[str, str] = {
    ".doc": "docx",
    ".xls": "xlsx",
    ".ppt": "pptx",
}


def read_or_convert_legacy(
    input_document: Path,
    runner: LibreOfficeRunner,
    *,
    target_format: str | None = None,
    max_output_bytes: int = 64 * 1024 * 1024,
) -> bytes:
    """Convert a legacy ``.doc``/``.xls``/``.ppt`` to its modern equivalent.

    If ``target_format`` is ``"pdf"``, converts to PDF instead.
    Returns the converted file bytes.
    """
    suffix = Path(input_document).suffix.lower()
    if target_format is None:
        target_format = _LEGACY_TARGETS.get(suffix, "pdf")
    with OperationTempRoot() as private_root:
        staged_input = private_root / ("input" + suffix)
        staged_input.write_bytes(Path(input_document).read_bytes())
        staged_input.chmod(stat.S_IREAD)
        output_dir = private_root / "output"
        output_dir.mkdir()
        try:
            output = runner.convert(staged_input, target_format, output_dir)
            output_bytes = output.stat().st_size
            if output_bytes > max_output_bytes:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "LibreOffice legacy output exceeds the requested byte ceiling.",
                    details={
                        "max_output_bytes": max_output_bytes,
                        "output_bytes": output_bytes,
                    },
                )
            return output.read_bytes()
        finally:
            staged_input.chmod(stat.S_IREAD | stat.S_IWRITE)
