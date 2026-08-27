"""Tracked-change read and accept/reject through the .NET helper.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.temp_roots import OperationTempRoot
from .runner import DotnetOpenXmlRunner


def read_revisions(
    input_docx: Path,
    runner: DotnetOpenXmlRunner,
    *,
    limit: int = 10_000,
    filters: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
    revision_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Read tracked changes (insertions/deletions/moves) keyed by revision id."""
    with OperationTempRoot() as private_root:
        staged = private_root / "input.docx"
        staged.write_bytes(Path(input_docx).read_bytes())
        payload: dict[str, Any] = {
            "input_path": str(staged),
            "max_revisions": limit,
        }
        if filters is not None:
            payload["filters"] = filters
        if scope is not None:
            payload["scope"] = scope
        if revision_ids is not None:
            payload["revision_ids"] = revision_ids
        result = runner.run(
            "--revisions-read",
            stdin_payload=payload,
        )
    if result.returncode != 0:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper --revisions-read exited non-zero.",
            details={"returncode": result.returncode},
        )
    payload = result.json()
    if not isinstance(payload, dict):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper returned non-object revisions JSON.",
        )
    revisions = payload.get("revisions", [])
    if type(revisions) is not list or len(revisions) > limit:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper revisions field is not a bounded list.",
        )
    return revisions


def accept_reject_revisions(
    input_docx: Path,
    output_docx: Path,
    revision_ids: list[str],
    action: str,
    runner: DotnetOpenXmlRunner,
) -> dict[str, Any]:
    """Accept or reject revisions by id. Returns diagnostics with matched/unmatched."""
    if action not in ("accept", "reject"):
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            f"Invalid revision action: {action}",
        )
    subcommand = "--revisions-accept" if action == "accept" else "--revisions-reject"
    with OperationTempRoot() as private_root:
        staged_input = private_root / "input.docx"
        staged_input.write_bytes(Path(input_docx).read_bytes())
        staged_output = private_root / "output.docx"
        result = runner.run(
            subcommand,
            stdin_payload={
                "input_path": str(staged_input),
                "output_path": str(staged_output),
                "revision_ids": revision_ids,
            },
        )
        if result.returncode != 0:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                f"dotnet helper {subcommand} exited non-zero.",
                details={"returncode": result.returncode},
            )
        if not staged_output.is_file():
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "dotnet helper produced no output file.",
            )
        payload = result.json()
        if not isinstance(payload, dict):
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "dotnet helper returned non-object JSON.",
            )
        Path(output_docx).write_bytes(staged_output.read_bytes())
    return {
        "matched_ids": payload.get("matched_ids", []),
        "unmatched_ids": payload.get("unmatched_ids", []),
    }
