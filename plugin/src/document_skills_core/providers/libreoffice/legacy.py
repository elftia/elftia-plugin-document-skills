"""Legacy ``.doc``/``.xls``/``.ppt`` read/convert via headless soffice.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path

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
        output_dir = private_root / "output"
        output_dir.mkdir()
        output = runner.convert(staged_input, target_format, output_dir)
        return output.read_bytes()
