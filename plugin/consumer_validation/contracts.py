"""Machine-readable report contract for independent consumers."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator, ValidationError


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
_OFFICE_GATE = {
    **_GATE,
    "allOf": [
        {
            "if": {
                "properties": {"availability": {"const": "available"}},
                "required": ["availability"],
            },
            "then": {
                "properties": {
                    "evidence": {
                        "type": "object",
                        "required": ["application", "version"],
                        "properties": {
                            "application": {"type": "string", "minLength": 1},
                            "version": {"type": "string", "minLength": 1},
                        },
                    }
                }
            },
        }
    ],
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
                "sha256": {
                    "oneOf": [
                        {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        {"type": "null"},
                    ]
                },
                "sha256_status": {
                    "enum": [
                        "not-computed-resource-limit",
                        "not-computed-non-exact-observation",
                    ]
                },
                "bytes": {
                    "oneOf": [
                        {"type": "integer", "minimum": 1},
                        {"type": "null"},
                    ]
                },
            },
            "additionalProperties": False,
            "oneOf": [
                {
                    "properties": {
                        "sha256": {"type": "string"},
                        "bytes": {"type": "integer", "minimum": 1},
                    },
                    "not": {"required": ["sha256_status"]},
                },
                {
                    "properties": {
                        "sha256": {"type": "null"},
                        "sha256_status": {"const": "not-computed-resource-limit"},
                        "bytes": {"type": "integer", "minimum": 1},
                    },
                    "required": ["sha256_status"],
                },
                {
                    "properties": {
                        "sha256": {"type": "null"},
                        "sha256_status": {
                            "const": "not-computed-non-exact-observation"
                        },
                        "bytes": {"type": "null"},
                    },
                    "required": ["sha256_status"],
                },
            ],
        },
        "status": {"enum": _OUTCOMES},
        "portable": _GATE,
        "office": _OFFICE_GATE,
        "office_acceptance": {"type": "boolean"},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "allOf": [
        {
            "if": {
                "properties": {
                    "artifact": {
                        "properties": {
                            "sha256_status": {
                                "const": "not-computed-resource-limit"
                            }
                        },
                        "required": ["sha256_status"],
                    }
                },
                "required": ["artifact"],
            },
            "then": {
                "properties": {
                    "format": {"const": "pdf"},
                    "status": {"const": "fail"},
                    "portable": {
                        "type": "object",
                        "properties": {
                            "outcome": {"const": "fail"},
                            "assertions": {
                                "type": "array",
                                "contains": {
                                    "type": "object",
                                    "required": ["id", "outcome", "evidence"],
                                    "properties": {
                                        "id": {"const": "pdf.resource-bounds"},
                                        "outcome": {"const": "fail"},
                                        "evidence": {
                                            "type": "object",
                                            "required": ["actual", "category", "maximum"],
                                            "properties": {
                                                "actual": {"type": "integer", "minimum": 1},
                                                "category": {"const": "artifact-byte-limit"},
                                                "maximum": {"type": "integer", "minimum": 1},
                                            },
                                        },
                                    },
                                },
                                "minContains": 1,
                            },
                        },
                        "required": ["outcome", "assertions"],
                    },
                },
                "required": ["format", "status", "portable"],
            },
        },
        {
            "if": {
                "properties": {
                    "artifact": {
                        "properties": {
                            "sha256_status": {
                                "const": "not-computed-non-exact-observation"
                            }
                        },
                        "required": ["sha256_status"],
                    }
                },
                "required": ["artifact"],
            },
            "then": {
                "properties": {
                    "format": {"const": "pdf"},
                    "status": {"const": "fail"},
                    "portable": {
                        "type": "object",
                        "properties": {
                            "outcome": {"const": "fail"},
                            "assertions": {
                                "type": "array",
                                "contains": {
                                    "type": "object",
                                    "required": ["id", "outcome", "evidence"],
                                    "properties": {
                                        "id": {"const": "consumer.source-preservation"},
                                        "outcome": {"const": "fail"},
                                        "evidence": {
                                            "type": "object",
                                            "required": ["identity_status"],
                                            "properties": {
                                                "identity_status": {
                                                    "const": "unavailable-non-exact-observation"
                                                }
                                            },
                                        },
                                    },
                                },
                                "minContains": 1,
                            },
                        },
                        "required": ["outcome", "assertions"],
                    },
                },
                "required": ["format", "status", "portable"],
            },
        },
    ],
    "additionalProperties": False,
}
_VALIDATOR = Draft202012Validator(CONSUMER_REPORT_SCHEMA)


def validate_consumer_report(report: dict[str, Any]) -> None:
    """Raise a deterministic schema error when a report is malformed."""

    _VALIDATOR.validate(report)
    _validate_nullable_identity_semantics(report)


def _validate_nullable_identity_semantics(report: dict[str, Any]) -> None:
    artifact = report["artifact"]
    status = artifact.get("sha256_status")
    if status == "not-computed-resource-limit":
        assertions = [
            item
            for item in report["portable"]["assertions"]
            if item["id"] == "pdf.resource-bounds"
        ]
        if len(assertions) != 1:
            raise ValidationError("resource-limit identity requires one resource assertion")
        assertion = assertions[0]
        evidence = assertion["evidence"]
        actual = evidence.get("actual")
        maximum = evidence.get("maximum")
        if (
            assertion["outcome"] != "fail"
            or evidence.get("category") != "artifact-byte-limit"
            or type(actual) is not int
            or type(maximum) is not int
            or actual != artifact["bytes"]
            or actual <= maximum
        ):
            raise ValidationError("resource-limit identity evidence is contradictory")
    elif status == "not-computed-non-exact-observation":
        assertions = [
            item
            for item in report["portable"]["assertions"]
            if item["id"] == "consumer.source-preservation"
        ]
        if len(assertions) != 1:
            raise ValidationError("non-exact identity requires one source assertion")
