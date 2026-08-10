"""Machine-readable report contract for independent consumers."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator


_OUTCOMES = ["pass", "fail", "unavailable", "not_run"]
_ASSERTION = {
    "type": "object",
    "required": ["id", "outcome", "evidence"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "outcome": {"enum": ["pass", "fail"]},
        "evidence": {"type": "object"},
        "message": {"type": "string"},
    },
    "additionalProperties": False,
}
_GATE = {
    "type": "object",
    "required": ["consumer", "availability", "outcome", "assertions", "warnings", "evidence"],
    "properties": {
        "consumer": {"type": "string", "minLength": 1},
        "availability": {"enum": ["available", "unavailable", "not_requested"]},
        "outcome": {"enum": _OUTCOMES},
        "assertions": {"type": "array", "items": _ASSERTION},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "object"},
    },
    "additionalProperties": False,
}
CONSUMER_REPORT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version",
        "format",
        "operation",
        "consumer_identity",
        "artifact",
        "status",
        "portable",
        "office",
        "office_acceptance",
        "warnings",
    ],
    "properties": {
        "schema_version": {"const": "1.0"},
        "format": {"enum": ["docx", "xlsx", "pptx", "pdf"]},
        "operation": {"type": "string", "minLength": 1},
        "consumer_identity": {"type": "string", "minLength": 1},
        "artifact": {
            "type": "object",
            "required": ["path", "sha256", "bytes"],
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "bytes": {"type": "integer", "minimum": 1},
            },
            "additionalProperties": False,
        },
        "status": {"enum": _OUTCOMES},
        "portable": _GATE,
        "office": _GATE,
        "office_acceptance": {"type": "boolean"},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}
_VALIDATOR = Draft202012Validator(CONSUMER_REPORT_SCHEMA)


def validate_consumer_report(report: dict[str, Any]) -> None:
    """Raise a deterministic schema error when a report is malformed."""

    _VALIDATOR.validate(report)
