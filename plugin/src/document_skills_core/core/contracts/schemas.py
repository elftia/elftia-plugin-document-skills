"""Checked-in schema loading, validation, and deterministic fingerprints."""

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .errors import DocumentSkillsError, ErrorCode

SCHEMA_FILES = {
    "operation-request": "operation-request.schema.json",
    "operation-result": "operation-result.schema.json",
    "doctor-report": "doctor-report.schema.json",
    "capability-report": "capability-report.schema.json",
    "validation-report": "validation-report.schema.json",
    "docx-template-pack": "docx-template-pack.schema.json",
}


class SchemaCatalog:
    def __init__(self, project_root: Path) -> None:
        self.schema_root = project_root.resolve() / "schemas"
        self._schemas = {
            name: json.loads((self.schema_root / filename).read_text(encoding="utf-8"))
            for name, filename in SCHEMA_FILES.items()
        }
        registry = Registry()
        for schema in self._schemas.values():
            registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
        self._registry = registry

    def validate(self, name: str, payload: Any) -> None:
        schema = self._schemas[name]
        errors = sorted(
            Draft202012Validator(schema, registry=self._registry).iter_errors(payload),
            key=lambda item: list(item.absolute_path),
        )
        if errors:
            issue = errors[0]
            path = ".".join(str(part) for part in issue.absolute_path) or "$"
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                f"{name} schema validation failed at {path}: {issue.message}",
                status="invalid_request" if name == "operation-request" else "failed",
                details={"schema": name, "path": path},
            )

    def fingerprint(self, name: str) -> str:
        canonical = json.dumps(
            self._schemas[name], ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def fingerprints(self) -> dict[str, str]:
        return {name: self.fingerprint(name) for name in sorted(self._schemas)}

    def validate_examples(self) -> None:
        for name, schema in self._schemas.items():
            for example in schema.get("examples", []):
                self.validate(name, example)
