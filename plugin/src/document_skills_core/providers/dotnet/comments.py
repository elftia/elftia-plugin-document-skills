"""Comment read, add, reply, and resolution through the .NET helper.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.temp_roots import OperationTempRoot
from .runner import DotnetOpenXmlRunner

# Tokens that MUST NEVER appear in a comment payload (active content).
_FORBIDDEN_COMMENT_TOKENS: tuple[str, ...] = (
    "http://", "https://", "www.", "javascript:", "file://",
    "<script", "<a ", "href=", "vbscript:",
)


def read_comments(
    input_docx: Path,
    runner: DotnetOpenXmlRunner,
    *,
    filter_id: str | None = None,
    filter_author: str | None = None,
    filter_range: str | None = None,
    max_comments: int = 10_000,
) -> list[dict[str, Any]]:
    """Read comments filtered by optional id, author, or range."""
    with OperationTempRoot() as private_root:
        staged = private_root / "input.docx"
        staged.write_bytes(Path(input_docx).read_bytes())
        payload: dict[str, Any] = {"input_path": str(staged)}
        payload["max_comments"] = max_comments
        if filter_id is not None:
            payload["filter_id"] = filter_id
        if filter_author is not None:
            payload["filter_author"] = filter_author
        if filter_range is not None:
            payload["filter_range"] = filter_range
        result = runner.run(
            "--comments-read",
            stdin_payload=payload,
        )
    if result.returncode != 0:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper --comments-read exited non-zero.",
            details={"returncode": result.returncode},
        )
    data = result.json()
    if not isinstance(data, dict):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper returned non-object comments JSON.",
        )
    comments = data.get("comments", [])
    if type(comments) is not list or len(comments) > max_comments:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper comments field is not a bounded list.",
        )
    return comments


def add_comment(
    input_docx: Path,
    output_docx: Path,
    comment_payload: dict[str, Any],
    runner: DotnetOpenXmlRunner,
) -> str:
    """Add a bounded comment. Rejects hyperlinks/scripts/executable content."""
    _validate_comment_payload(comment_payload)
    with OperationTempRoot() as private_root:
        staged_input = private_root / "input.docx"
        staged_input.write_bytes(Path(input_docx).read_bytes())
        staged_output = private_root / "output.docx"
        result = runner.run(
            "--comments-add",
            stdin_payload={
                "input_path": str(staged_input),
                "output_path": str(staged_output),
                "comment": comment_payload,
            },
        )
        if result.returncode != 0:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "dotnet helper --comments-add exited non-zero.",
                details={"returncode": result.returncode},
            )
        if not staged_output.is_file():
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "dotnet helper produced no output file.",
            )
        data = result.json()
        if not isinstance(data, dict) or "comment_id" not in data:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "dotnet helper returned no comment_id.",
            )
        Path(output_docx).write_bytes(staged_output.read_bytes())
    return str(data["comment_id"])


def resolve_comment(
    input_docx: Path,
    output_docx: Path,
    comment_id: str,
    resolved: bool,
    runner: DotnetOpenXmlRunner,
) -> dict[str, Any]:
    """Set one root comment thread's resolved state in a private candidate."""

    with OperationTempRoot() as private_root:
        staged_input = private_root / "input.docx"
        staged_input.write_bytes(Path(input_docx).read_bytes())
        staged_output = private_root / "output.docx"
        result = runner.run(
            "--comments-resolve",
            stdin_payload={
                "input_path": str(staged_input),
                "output_path": str(staged_output),
                "comment_id": comment_id,
                "resolved": resolved,
            },
        )
        if result.returncode != 0:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "dotnet helper --comments-resolve exited non-zero.",
                details={"returncode": result.returncode},
            )
        if not staged_output.is_file():
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "dotnet helper produced no resolved comment output file.",
            )
        data = result.json()
        if (
            type(data) is not dict
            or data.get("comment_id") != comment_id
            or data.get("resolved") is not resolved
            or set(data) != {"comment_id", "resolved"}
        ):
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "dotnet helper returned an invalid comment resolution result.",
            )
        Path(output_docx).write_bytes(staged_output.read_bytes())
    return {"comment_id": comment_id, "resolved": resolved}


def _validate_comment_payload(payload: dict[str, Any]) -> None:
    """Reject any payload that attempts to inject active content."""
    text = str(payload.get("text", ""))
    lowered = text.lower()
    for token in _FORBIDDEN_COMMENT_TOKENS:
        if token.lower() in lowered:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Comment payload contains a forbidden hyperlink or script token.",
                details={"token": token},
            )
