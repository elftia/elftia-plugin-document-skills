"""Advanced template fidelity through the .NET helper.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.temp_roots import OperationTempRoot
from .runner import DotnetOpenXmlRunner


def apply_template_advanced(
    input_docx: Path,
    output_docx: Path,
    variables: dict[str, str],
    runner: DotnetOpenXmlRunner,
) -> dict[str, Any]:
    """Apply advanced template operations via the OpenXML typed object model."""
    with OperationTempRoot() as private_root:
        staged_input = private_root / "input.docx"
        staged_input.write_bytes(Path(input_docx).read_bytes())
        staged_output = private_root / "output.docx"
        result = runner.run(
            "--template-apply",
            stdin_payload={
                "input_path": str(staged_input),
                "output_path": str(staged_output),
                "variables": variables,
            },
        )
        if result.returncode != 0:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "dotnet helper --template-apply exited non-zero.",
                details={"returncode": result.returncode},
            )
        if not staged_output.is_file():
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "dotnet helper produced no output file.",
            )
        data = result.json()
        if not isinstance(data, dict):
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "dotnet helper returned non-object JSON.",
            )
        Path(output_docx).write_bytes(staged_output.read_bytes())
    return {
        "applied_variables": data.get("applied_variables", []),
        "backend": "dotnet-openxml",
    }
