"""Stable error catalog for machine-readable results."""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    REQUEST_INVALID = "DS_REQUEST_INVALID"
    OPERATION_UNKNOWN = "DS_OPERATION_UNKNOWN"
    RUNTIME_UNAVAILABLE = "DS_RUNTIME_UNAVAILABLE"
    INPUT_NOT_FOUND = "DS_INPUT_NOT_FOUND"
    OUTPUT_EQUALS_INPUT = "DS_OUTPUT_EQUALS_INPUT"
    PATH_UNSAFE = "DS_PATH_UNSAFE"
    ARCHIVE_UNSAFE = "DS_ARCHIVE_UNSAFE"
    PROVIDER_UNAVAILABLE = "DS_PROVIDER_UNAVAILABLE"
    ENHANCEMENT_REQUIRED = "DS_ENHANCEMENT_REQUIRED"
    PROCESS_TIMEOUT = "DS_PROCESS_TIMEOUT"
    PROVIDER_FAILED = "DS_PROVIDER_FAILED"
    VALIDATION_FAILED = "DS_VALIDATION_FAILED"
    INTERNAL_ERROR = "DS_INTERNAL_ERROR"


class DocumentSkillsError(Exception):
    """Expected error converted to a stable result instead of a traceback contract."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status: str = "failed",
        details: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}
        self.validation = validation

    def record(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": str(self), "details": self.details}
