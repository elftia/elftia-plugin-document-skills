"""OOXML schema validation through the .NET helper.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.temp_roots import OperationTempRoot
from .runner import DotnetOpenXmlRunner


def validate_schema(
    input_docx: Path,
    runner: DotnetOpenXmlRunner,
    *,
    max_errors: int = 100,
) -> dict[str, Any]:
    """Run the OpenXML SDK schema validator. Returns valid + per-part errors."""
    with OperationTempRoot() as private_root:
        staged = private_root / "input.docx"
        staged.write_bytes(Path(input_docx).read_bytes())
        result = runner.run(
            "--schema-validate",
            stdin_payload={"input_path": str(staged), "max_errors": max_errors},
        )
    if result.returncode != 0:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper --schema-validate exited non-zero.",
            details={"returncode": result.returncode},
        )
    data = result.json()
    if not isinstance(data, dict):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper returned non-object schema JSON.",
        )
    valid = data.get("valid")
    if not isinstance(valid, bool):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper schema valid field is not boolean.",
        )
    errors = data.get("errors", [])
    if type(errors) is not list or len(errors) > max_errors:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper schema errors field is not a bounded list.",
        )
    return {"valid": valid, "errors": errors}
