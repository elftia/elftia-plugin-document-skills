"""Stable public errors for identity-bound artifact promotion."""

from __future__ import annotations

from pathlib import Path

from ..contracts.errors import DocumentSkillsError, ErrorCode
from .parent_anchor import ParentSafetyError


def destination_transaction_busy() -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Destination is being modified by another transaction.",
        details={"destination_race": True, "destination_transaction_busy": True},
    )


def destination_transaction_unavailable(error: OSError) -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Exclusive destination transaction could not be established.",
        details={
            "destination_race": True,
            "destination_transaction_unavailable": True,
            "reason": type(error).__name__,
        },
    )


def internal_target_occupied(role: str, path: Path) -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        f"The selected internal {role} target is occupied.",
        details={
            "destination_race": True,
            "internal_target_occupied": True,
            "internal_target_role": role,
            "internal_target_path": str(path),
        },
    )


def no_replace_unavailable(error: OSError) -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Atomic no-replace promotion is unavailable for this destination.",
        details={
            "destination_race": True,
            "atomic_no_replace_unavailable": True,
            "reason": type(error).__name__,
            "errno": error.errno,
        },
    )


def parent_safety_error(error: ParentSafetyError) -> DocumentSkillsError:
    preflight = error.phase in {"preflight", "capture"} and error.reason in {
        "destination_parent_redirected",
        "destination_parent_not_directory",
        "destination_parent_not_plain_directory",
        "destination_path_escape",
    }
    return DocumentSkillsError(
        ErrorCode.PATH_UNSAFE if preflight else ErrorCode.VALIDATION_FAILED,
        "The physical destination parent is unsafe or changed during promotion.",
        status="invalid_request" if preflight else "failed",
        details={
            "destination_race": not preflight,
            "destination_parent_changed": not preflight,
            "destination_parent_safety_failure": True,
            "parent_phase": error.phase,
            "parent_reason": error.reason,
            "parent_original_path": str(error.original_path),
            "parent_current_path": (
                str(error.current_path) if error.current_path is not None else None
            ),
        },
    )
