"""DOCX/PPTX page/slide render to image for visual QA.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path

from ...core.io.temp_roots import OperationTempRoot
from .input_snapshot import private_libreoffice_input
from .output import read_provider_output
from .runner import LibreOfficeRunner


def render_to_image(
    input_document: Path,
    runner: LibreOfficeRunner,
) -> bytes:
    """Render a DOCX or PPTX to PNG via headless soffice.

    Returns the rendered image bytes for the visual-validation gate.
    """
    with private_libreoffice_input(
        input_document,
        operation="libreoffice.render-image",
    ) as snapshot:
        return render_snapshot_to_image(snapshot.path, runner)


def render_snapshot_to_image(
    input_snapshot: Path,
    runner: LibreOfficeRunner,
) -> bytes:
    """Render an already screened DOCX/PPTX snapshot without copying it."""

    with OperationTempRoot() as private_root:
        output_dir = private_root / "output"
        output_dir.mkdir()
        output = runner.convert(input_snapshot, "png", output_dir)
        return read_provider_output(output, "png")
