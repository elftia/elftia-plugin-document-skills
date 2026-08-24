"""Legacy ``.doc``/``.xls``/``.ppt`` read/convert via headless soffice.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.temp_roots import OperationTempRoot
from .input_snapshot import private_libreoffice_input
from .output import read_provider_output
from .runner import LibreOfficeRunner

_LEGACY_TARGETS: dict[str, str] = {
    "doc": "docx",
    "xls": "xlsx",
    "ppt": "pptx",
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
    with private_libreoffice_input(
        input_document,
        operation="libreoffice.read-legacy",
    ) as snapshot:
        return convert_legacy_snapshot(
            snapshot.path,
            runner,
            source_format=snapshot.actual_format,
            target_format=target_format,
        )


def convert_legacy_snapshot(
    input_snapshot: Path,
    runner: LibreOfficeRunner,
    *,
    source_format: str,
    target_format: str | None = None,
) -> bytes:
    """Convert one screened legacy compound-file snapshot."""

    default_target = _LEGACY_TARGETS[source_format]
    target_format = target_format or default_target
    if target_format not in {default_target, "pdf"}:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "LibreOffice legacy target does not match the detected source format.",
            status="invalid_request",
            details={
                "source_format": source_format,
                "target_format": target_format,
                "accepted_targets": [default_target, "pdf"],
            },
        )
    with OperationTempRoot() as private_root:
        output_dir = private_root / "output"
        output_dir.mkdir()
        output = runner.convert(input_snapshot, target_format, output_dir)
        return read_provider_output(output, target_format)
