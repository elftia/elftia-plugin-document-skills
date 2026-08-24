"""Deterministic planning-only JSON output for PPTX outlines."""

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.contracts.serialization import render_json_bytes


def write_outline(path: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    """Write a versioned outline that cannot be mistaken for a presentation."""

    plan = {
        "schema_version": "1.0",
        "kind": "pptx-outline",
        "artifact_type": "planning-json",
        "presentation_generated": False,
        "title": arguments["title"],
        "subtitle": arguments["subtitle"],
        "audience": arguments["audience"],
        "objective": arguments["objective"],
        "slides": [
            {
                "number": index,
                **slide,
            }
            for index, slide in enumerate(arguments["slides"], 1)
        ],
    }
    path.write_bytes(render_json_bytes(plan))
    _validate_outline(path, plan)
    return plan


def outline_validation(path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    payload = path.read_bytes()
    gates = [
        gate_record(
            "artifact.exists-size",
            "pass",
            evidence={"bytes": len(payload), "sha256": sha256(payload).hexdigest()},
        ),
        gate_record(
            "operation.pptx-outline-planning",
            "pass",
            evidence={
                "artifact_type": plan["artifact_type"],
                "presentation_generated": False,
                "schema_version": plan["schema_version"],
                "slides": len(plan["slides"]),
            },
        ),
        gate_record(
            "visual.render",
            "not_applicable",
            required=False,
            evidence={"reason": "The output is planning JSON, not a presentation."},
        ),
        gate_record(
            "schema.full",
            "not_applicable",
            required=False,
            evidence={"reason": "OpenXML validation does not apply to planning JSON."},
        ),
    ]
    return {"schema_version": "1.0", "status": "pass", "gates": gates}


def _validate_outline(path: Path, expected: dict[str, Any]) -> None:
    try:
        reopened = json.loads(path.read_bytes().decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "The staged PPTX outline could not be reopened as strict JSON.",
            status="failed",
        ) from error
    if reopened != expected or reopened.get("presentation_generated") is not False:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "The staged PPTX outline does not match the requested plan.",
            status="failed",
        )
