"""Fail-closed normalization for provider and runtime detector records."""

from dataclasses import dataclass
from typing import Any

from ..contracts.errors import DocumentSkillsError, ErrorCode
from ..contracts.provider_values import normalize_provider_json
from .catalog import DetectionEvidence

MAX_PROVIDER_ID_BYTES = 128
MAX_PROVIDER_VERSION_BYTES = 256
MAX_PROVIDER_REASON_BYTES = 512
MAX_PROVIDER_PATH_BYTES = 1_024
INVALID_DETECTOR_REASON = "Provider detector returned invalid data."
FAILED_DETECTOR_REASON = "Provider detector failed."

_FIELD_TYPES: dict[str, tuple[type, ...]] = {
    "id": (str,),
    "available": (bool,),
    "version": (str, type(None)),
    "reason": (str, type(None)),
    "required": (bool,),
    "path": (str, type(None)),
}


@dataclass(frozen=True)
class DetectorFailure:
    provider_id: str
    reason: str
    exception_name: str

    def as_error(self) -> DocumentSkillsError:
        return DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Provider detection failed.",
            details={
                "provider": self.provider_id,
                "phase": "detect",
                "reason": self.reason,
                "exception": self.exception_name,
            },
        )


def normalize_detector_state(
    value: Any,
    *,
    trusted_id: str,
    required: bool,
) -> dict[str, Any]:
    """Copy an untrusted detector value into the canonical plain record."""
    if type(value) is not dict:
        raise TypeError("detector state must be a plain object")
    normalized = normalize_provider_json(value)
    if set(normalized) != set(_FIELD_TYPES):
        raise ValueError("detector state fields do not match the canonical contract")
    for field_name, expected in _FIELD_TYPES.items():
        if type(normalized[field_name]) not in expected:
            raise TypeError(f"detector state field has invalid type: {field_name}")
    if normalized["id"] != trusted_id:
        raise ValueError("detector state id differs from the registered provider")
    if normalized["required"] is not required:
        raise ValueError("detector state required flag differs from the registry")
    _bounded_text(normalized["id"], MAX_PROVIDER_ID_BYTES)
    _bounded_text(normalized["version"], MAX_PROVIDER_VERSION_BYTES)
    _bounded_text(normalized["reason"], MAX_PROVIDER_REASON_BYTES)
    _bounded_text(normalized["path"], MAX_PROVIDER_PATH_BYTES)
    if normalized["available"] and normalized["reason"] is not None:
        raise ValueError("available detector state cannot contain a failure reason")
    if not normalized["available"] and not normalized["reason"]:
        raise ValueError("unavailable detector state requires a bounded reason")
    return normalized


def normalize_detection_evidence(value: Any) -> DetectionEvidence:
    """Normalize detector-owned availability evidence without identity fields."""
    if isinstance(value, DetectionEvidence):
        candidate = value
    elif type(value) is dict and set(value) == {
        "available",
        "version",
        "reason",
        "path",
    }:
        candidate = DetectionEvidence(
            available=value["available"],
            version=value["version"],
            reason=value["reason"],
            path=value["path"],
        )
    else:
        raise TypeError("detector must return exact DetectionEvidence")
    if type(candidate.available) is not bool:
        raise TypeError("detector availability must be boolean")
    _bounded_text(candidate.version, MAX_PROVIDER_VERSION_BYTES)
    _bounded_text(candidate.reason, MAX_PROVIDER_REASON_BYTES)
    _bounded_text(candidate.path, MAX_PROVIDER_PATH_BYTES)
    if candidate.available and candidate.reason is not None:
        raise ValueError("available evidence cannot include a reason")
    if not candidate.available and not candidate.reason:
        raise ValueError("unavailable evidence requires a reason")
    return candidate


def unavailable_detector_state(
    trusted_id: str,
    *,
    required: bool,
    reason: str,
    fallback_version: Any = None,
) -> dict[str, Any]:
    """Build a trusted schema-valid unavailable record without provider methods."""
    version = fallback_version if type(fallback_version) is str else None
    if version is not None:
        try:
            _bounded_text(version, MAX_PROVIDER_VERSION_BYTES)
        except (TypeError, UnicodeError, ValueError):
            version = None
    return {
        "id": _trusted_id(trusted_id),
        "available": False,
        "version": version,
        "reason": reason,
        "required": required,
        "path": None,
    }


def detector_failure(
    trusted_id: str,
    error: BaseException,
    *,
    invalid_data: bool,
) -> DetectorFailure:
    return DetectorFailure(
        provider_id=_trusted_id(trusted_id),
        reason=INVALID_DETECTOR_REASON if invalid_data else FAILED_DETECTOR_REASON,
        exception_name=type(error).__name__[:64],
    )


def normalize_detector_records(values: Any) -> list[dict[str, Any]]:
    """Normalize an untrusted report list without invoking mapping methods."""
    if type(values) is not list:
        return [
            unavailable_detector_state(
                "invalid-provider",
                required=False,
                reason=INVALID_DETECTOR_REASON,
            )
        ]
    records: list[dict[str, Any]] = []
    for value in values:
        trusted_id = "invalid-provider"
        required = False
        if type(value) is dict:
            raw_id = value["id"] if "id" in value else None
            raw_required = value["required"] if "required" in value else None
            if type(raw_id) is str:
                trusted_id = raw_id
            if type(raw_required) is bool:
                required = raw_required
        try:
            records.append(
                normalize_detector_state(
                    value,
                    trusted_id=trusted_id,
                    required=required,
                )
            )
        except Exception:
            records.append(
                unavailable_detector_state(
                    trusted_id,
                    required=required,
                    reason=INVALID_DETECTOR_REASON,
                )
            )
    return records


def _trusted_id(value: str) -> str:
    if type(value) is not str:
        return "invalid-provider"
    try:
        _bounded_text(value, MAX_PROVIDER_ID_BYTES)
    except (TypeError, UnicodeError, ValueError):
        return "invalid-provider"
    return value


def _bounded_text(value: str | None, maximum: int) -> None:
    if value is None:
        return
    if type(value) is not str:
        raise TypeError("detector text must be a plain string")
    if len(value.encode("utf-8", errors="strict")) > maximum:
        raise ValueError("detector text exceeds its byte limit")
