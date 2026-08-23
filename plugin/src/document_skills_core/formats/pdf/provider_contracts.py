"""Strict contracts for provider-backed PDF security and optimization."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

MAX_PASSWORD_BYTES = 127
PDF_PERMISSION_NAMES = frozenset(
    {
        "annotate",
        "assemble",
        "extract",
        "fill_forms",
        "high_quality_print",
        "modify",
        "print",
        "accessibility",
    }
)


def parse_provider_arguments(
    operation: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    if operation == "pdf.encrypt":
        return _parse_encrypt(value)
    if operation == "pdf.decrypt":
        return _parse_decrypt(value)
    if operation == "pdf.compress":
        return _parse_compress(value)
    raise AssertionError(f"unsupported provider-backed PDF operation: {operation}")


def _parse_encrypt(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        value,
        {
            "user_password",
            "owner_password",
            "algorithm",
            "permissions",
            "encrypt_metadata",
        },
    )
    user_password = _password(value.get("user_password"), "user_password")
    owner_password = _password(value.get("owner_password"), "owner_password")
    if user_password == owner_password:
        _invalid(
            "Owner and user passwords must be distinct.",
            field="owner_password",
        )
    algorithm = value.get("algorithm", "AES-256-R5")
    if algorithm != "AES-256-R5":
        _enhancement(
            "Only strong AES-256-R5 encryption is implemented.",
            field="algorithm",
            requested_algorithm=algorithm,
        )
    permissions = value.get("permissions", sorted(PDF_PERMISSION_NAMES))
    if type(permissions) is not list or len(permissions) > len(PDF_PERMISSION_NAMES):
        _invalid("permissions must be a bounded array.", field="permissions")
    if any(type(item) is not str or item not in PDF_PERMISSION_NAMES for item in permissions):
        _invalid("permissions contains an unknown permission.", field="permissions")
    if len(set(permissions)) != len(permissions):
        _invalid("permissions must not contain duplicates.", field="permissions")
    encrypt_metadata = value.get("encrypt_metadata", True)
    if type(encrypt_metadata) is not bool:
        _invalid("encrypt_metadata must be boolean.", field="encrypt_metadata")
    if encrypt_metadata is not True:
        _enhancement(
            "Unencrypted metadata is not implemented by the accepted provider path.",
            field="encrypt_metadata",
        )
    return {
        "user_password": user_password,
        "owner_password": owner_password,
        "algorithm": algorithm,
        "permissions": sorted(permissions),
        "encrypt_metadata": True,
    }


def _parse_decrypt(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"password"})
    return {"password": _password(value.get("password"), "password")}


def _parse_compress(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"mode"})
    mode = value.get("mode", "lossless")
    if mode not in {"lossless", "balanced", "aggressive"}:
        _invalid("Unknown compression mode.", field="mode")
    if mode != "lossless":
        _enhancement(
            "Only evidence-backed lossless PDF compression is implemented.",
            field="mode",
            requested_mode=mode,
        )
    return {"mode": mode}


def _password(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        _invalid("Password must be a non-empty string.", field=field)
    encoded = value.encode("utf-8", errors="strict")
    if len(encoded) > MAX_PASSWORD_BYTES:
        _invalid(
            f"Password exceeds the {MAX_PASSWORD_BYTES}-byte limit.",
            field=field,
        )
    if "\x00" in value:
        _invalid("Password must not contain NUL.", field=field)
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown PDF operation argument.", unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
