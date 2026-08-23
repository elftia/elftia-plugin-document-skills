"""Optional OpenXML SDK schema gate for staged PPTX candidates."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.models import gate_record


def validate_schema_gate(path: Path, provider: Any) -> dict[str, Any]:
    evidence = _detection_evidence(provider)
    version = _evidence_version(evidence)
    if evidence is None or evidence.available is not True:
        return gate_record(
            "schema.full",
            "unavailable",
            required=False,
            validator="dotnet-openxml",
            version=version,
            evidence={"reason": _unavailable_reason(evidence)},
            warnings=["Optional OpenXML SDK schema validation is unavailable."],
        )
    result = provider.try_validate_schema(path)
    if type(result) is not dict:
        return gate_record(
            "schema.full",
            "fail",
            required=True,
            validator="dotnet-openxml",
            version=version,
            evidence={"reason": "schema-provider-failed"},
        )
    valid = result.get("valid") is True
    errors = result.get("errors", [])
    return gate_record(
        "schema.full",
        "pass" if valid else "fail",
        required=True,
        validator="dotnet-openxml",
        version=version,
        evidence={
            "error_count": len(errors) if type(errors) is list else 0,
            "errors": errors[:100] if type(errors) is list else [],
            "valid": valid,
        },
    )


def with_schema_gate(
    validation: dict[str, Any],
    schema_gate: dict[str, Any],
) -> dict[str, Any]:
    gates = [
        schema_gate if gate["id"] == "schema.full" else gate
        for gate in validation["gates"]
    ]
    failed = any(
        gate["required"] and gate["outcome"] != "pass"
        for gate in gates
    )
    return {
        **validation,
        "gates": gates,
        "status": "fail" if failed else "pass",
    }


def _detection_evidence(provider: Any) -> Any:
    if provider is None or not hasattr(provider, "detect"):
        return None
    try:
        return provider.detect()
    except Exception:
        return None


def _evidence_version(evidence: Any) -> str | None:
    version = None if evidence is None else getattr(evidence, "version", None)
    return version if type(version) is str else None


def _unavailable_reason(evidence: Any) -> str:
    reason = None if evidence is None else getattr(evidence, "reason", None)
    return reason if type(reason) is str and reason else "OpenXML SDK provider is unavailable."
