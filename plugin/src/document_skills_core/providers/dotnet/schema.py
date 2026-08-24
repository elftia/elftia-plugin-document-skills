"""OOXML schema validation through the .NET helper.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.temp_roots import OperationTempRoot
from .runner import DotnetOpenXmlRunner


def validate_schema(
    input_document: Path,
    runner: DotnetOpenXmlRunner,
) -> dict[str, Any]:
    """Run the OpenXML SDK schema validator. Returns valid + per-part errors."""
    suffix = Path(input_document).suffix.casefold()
    if suffix not in {".docm", ".docx", ".dotm", ".dotx", ".potm", ".potx", ".pptm", ".pptx"}:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "OpenXML schema validation received an unsupported extension.",
        )
    with OperationTempRoot() as private_root:
        staged = private_root / f"input{suffix}"
        staged.write_bytes(Path(input_document).read_bytes())
        result = runner.run(
            "--schema-validate",
            stdin_payload={"input_path": str(staged)},
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
    raw_errors = data.get("errors", [])
    if not isinstance(raw_errors, list) or len(raw_errors) > 100:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper schema errors field is not a list.",
        )
    errors = [_schema_error(item) for item in raw_errors]
    if valid == bool(errors):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper schema validity contradicts its error list.",
        )
    return {"valid": valid, "errors": errors}


def _schema_error(value: Any) -> dict[str, str]:
    if type(value) is not dict:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper schema error entry is invalid.",
        )
    result: dict[str, str] = {}
    for field, ceiling in {
        "description": 2_048,
        "error_type": 128,
        "part": 512,
        "path": 1_024,
    }.items():
        item = value.get(field, "")
        if type(item) is not str or len(item) > ceiling:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "dotnet helper schema error field is invalid.",
                details={"field": field},
            )
        result[field] = item
    return result
