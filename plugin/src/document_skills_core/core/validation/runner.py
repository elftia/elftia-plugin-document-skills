"""Structured validation gate orchestration."""

from collections.abc import Callable
from pathlib import Path
import time
from typing import Any
import zipfile

from defusedxml.ElementTree import fromstring

from ..contracts.errors import DocumentSkillsError
from ..contracts.models import gate_record
from ..io.archive import DangerousContentPolicy, inspect_ooxml
from ..io.paths import sha256_file

_OOXML_REQUIRED = {
    ".docx": "word/document.xml",
    ".xlsx": "xl/workbook.xml",
    ".pptx": "ppt/presentation.xml",
    ".pptm": "ppt/presentation.xml",
}
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class ValidationRunner:
    def __init__(self) -> None:
        self.gates: list[dict[str, Any]] = []

    def run_gate(
        self,
        gate_id: str,
        check: Callable[[], dict[str, Any]],
        *,
        required: bool = True,
        validator: str = "document-skills-core",
    ) -> None:
        started = time.monotonic()
        try:
            evidence = check()
            outcome = "pass"
            warnings: list[str] = []
        except ValidationUnavailable as error:
            evidence = {"reason": str(error)}
            outcome = "unavailable"
            warnings = [str(error)]
        except DocumentSkillsError as error:
            evidence = {
                "reason": error.code.value,
                "message": str(error)[:512],
                **error.details,
            }
            outcome = "fail"
            warnings = []
        except Exception as error:
            evidence = {"reason": type(error).__name__, "message": str(error)[:512]}
            outcome = "fail"
            warnings = []
        self.gates.append(
            gate_record(
                gate_id,
                outcome,
                required=required,
                validator=validator,
                duration_ms=int((time.monotonic() - started) * 1000),
                evidence=evidence,
                warnings=warnings,
            )
        )

    def unavailable(self, gate_id: str, reason: str, *, required: bool = False) -> None:
        self.gates.append(
            gate_record(
                gate_id,
                "unavailable",
                required=required,
                evidence={"reason": reason},
                warnings=[reason],
            )
        )

    def report(self) -> dict[str, Any]:
        required_fail = any(
            gate["required"] and gate["outcome"] != "pass"
            for gate in self.gates
        )
        return {
            "schema_version": "1.0",
            "status": "fail" if required_fail else "pass",
            "gates": self.gates,
        }


class ValidationUnavailable(RuntimeError):
    pass


def validate_artifact(
    path: str | Path,
    *,
    expected_format: str | None = None,
    source_path: str | Path | None = None,
    source_sha256: str | None = None,
    reopen: Callable[[Path], Any] | None = None,
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] | None = None,
    visual_available: bool = False,
    schema_available: bool = False,
    allow_dangerous_inventory: bool = False,
    dangerous_policy: DangerousContentPolicy | str | None = None,
) -> dict[str, Any]:
    artifact = Path(path).resolve()
    extension = artifact.suffix.lower()
    format_id = (expected_format or extension.lstrip(".")).lower()
    runner = ValidationRunner()
    runner.run_gate("artifact.exists-size", lambda: _existence(artifact))
    runner.run_gate("artifact.magic-extension", lambda: _magic(artifact, format_id))
    if extension in _OOXML_REQUIRED:
        content_policy = (
            DangerousContentPolicy(dangerous_policy)
            if dangerous_policy is not None
            else DangerousContentPolicy.PRESERVE_DISABLED
            if allow_dangerous_inventory
            else DangerousContentPolicy.REJECT
        )
        runner.run_gate(
            "ooxml.archive-xml",
            lambda: inspect_ooxml(
                artifact,
                dangerous_policy=content_policy,
            ),
        )
        runner.run_gate("ooxml.content-types", lambda: _content_types(artifact))
        runner.run_gate("ooxml.relationships", lambda: _relationships(artifact))
        runner.run_gate(
            "ooxml.required-part",
            lambda: _required_part(artifact, _OOXML_REQUIRED[extension]),
        )
    if reopen is None:
        runner.unavailable(
            "provider.reopen",
            "No accepted format-provider reopen hook is registered.",
            required=True,
        )
    else:
        runner.run_gate("provider.reopen", lambda: {"result": reopen(artifact)})
    if source_path is not None and source_sha256 is not None:
        runner.run_gate(
            "source.preservation",
            lambda: _source_preservation(Path(source_path), source_sha256),
        )
    else:
        runner.gates.append(
            gate_record(
                "source.preservation",
                "not_applicable",
                required=False,
                evidence={"reason": "No source artifact was supplied."},
            )
        )
    for assertion_id, assertion in assertions or []:
        runner.run_gate(f"operation.{assertion_id}", lambda item=assertion: item(artifact))
    runner.unavailable(
        "visual.render",
        "No accepted visual-render provider is available.",
        required=False,
    ) if not visual_available else runner.gates.append(
        gate_record("visual.render", "not_run", required=False, evidence={})
    )
    runner.unavailable(
        "schema.full",
        "No accepted full-schema validator is available.",
        required=False,
    ) if not schema_available else runner.gates.append(
        gate_record("schema.full", "not_run", required=False, evidence={})
    )
    return runner.report()


def _existence(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("Artifact is missing or empty.")
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def _magic(path: Path, format_id: str) -> dict[str, Any]:
    with path.open("rb") as handle:
        magic = handle.read(8)
    expected_zip = format_id in {"docx", "xlsx", "pptx"}
    valid = magic.startswith(b"PK") if expected_zip else magic.startswith(b"%PDF-")
    if not valid:
        raise ValueError(f"Magic bytes do not match {format_id}.")
    return {"format": format_id, "magic": magic.hex()}


def _content_types(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        payload = archive.read("[Content_Types].xml")
    root = fromstring(payload)
    if not root.tag.endswith("Types"):
        raise ValueError("Invalid OOXML content-types root.")
    return {"content_type_entries": len(root)}


def _relationships(path: Path) -> dict[str, Any]:
    external: list[str] = []
    dangerous: list[str] = []
    with zipfile.ZipFile(path) as archive:
        relationship_parts = [name for name in archive.namelist() if name.endswith(".rels")]
        for name in relationship_parts:
            root = fromstring(archive.read(name))
            for relationship in root.findall(f"{_REL_NS}Relationship"):
                target_mode = relationship.attrib.get("TargetMode")
                target = relationship.attrib.get("Target", "")
                rel_type = relationship.attrib.get("Type", "")
                if target_mode == "External":
                    external.append(target)
                lowered = f"{target} {rel_type}".lower()
                if any(token in lowered for token in ("oleobject", "attachedtemplate", "dde")):
                    dangerous.append(target or rel_type)
    if dangerous:
        raise ValueError(f"Dangerous relationships detected: {len(dangerous)}")
    return {"relationship_parts": len(relationship_parts), "external_targets": external}


def _required_part(path: Path, part: str) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        if part not in archive.namelist():
            raise ValueError(f"Required part is missing: {part}")
    return {"required_part": part}


def _source_preservation(path: Path, expected_sha256: str) -> dict[str, Any]:
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ValueError("Source SHA-256 changed.")
    return {"sha256": actual}
