"""DOCX/PPTX page/slide render to image for visual QA.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.temp_roots import OperationTempRoot
from .runner import LibreOfficeRunner

_RENDERABLE_SUFFIXES = {".docx", ".pptx"}


def render_to_image(
    input_document: Path,
    runner: LibreOfficeRunner,
) -> bytes:
    """Render a DOCX or PPTX to PNG via headless soffice.

    Returns the rendered image bytes for the visual-validation gate.
    """
    suffix = Path(input_document).suffix.casefold()
    if suffix not in _RENDERABLE_SUFFIXES:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "LibreOffice image rendering accepts only DOCX or PPTX input.",
            status="invalid_request",
            details={"suffix": suffix},
        )
    with OperationTempRoot() as private_root:
        staged_input = private_root / ("input" + suffix)
        staged_input.write_bytes(Path(input_document).read_bytes())
        output_dir = private_root / "output"
        output_dir.mkdir()
        output = runner.convert(staged_input, "png", output_dir)
        return output.read_bytes()
