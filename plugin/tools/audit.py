"""Deterministic structural, fixture, provenance, and release inventory audits."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .audit_commands import audit_agent_commands
from .audit_execution import audit_execution_boundary, is_forbidden_execution_path
from .audit_provenance import audit_clean_room, audit_provenance
from .release_inventory import (
    FORBIDDEN_RELEASE_NAMES,
    release_artifacts,
    release_inventory as build_release_inventory,
)
from .supply_chain import build_sbom, canonical_json
from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

PUBLIC_SKILLS = ["document-docx", "document-pdf", "document-pptx", "document-xlsx"]
FORBIDDEN_NAMES = FORBIDDEN_RELEASE_NAMES


def run_audits(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    inventory = release_inventory(root)
    errors: list[dict[str, str]] = []
    checks = {
        "public_skills": _capture(errors, "public_skills", lambda: audit_skills(root)),
        "manifests": _capture(errors, "manifests", lambda: audit_manifests(root)),
        "commands": _capture(errors, "commands", lambda: audit_commands(root)),
        "inventory": _capture(
            errors, "inventory", lambda: audit_inventory(root, inventory)
        ),
        "execution_boundary": _capture(
            errors,
            "execution_boundary",
            lambda: audit_execution_boundary(root, inventory),
        ),
        "fixtures": _capture(errors, "fixtures", lambda: audit_fixtures(root)),
        "provenance": _capture(
            errors, "provenance", lambda: audit_provenance(root, inventory)
        ),
        "clean_room": _capture(errors, "clean_room", lambda: audit_clean_room(root)),
        "sbom": _capture(errors, "sbom", lambda: audit_sbom(root)),
    }
    return {
        "schema_version": "1.0",
        "status": "pass" if not errors else "fail",
        "checks": checks,
        "errors": errors,
    }


def audit_skills(root: Path) -> dict[str, Any]:
    skills_root = root / "skills"
    names = sorted(
        child.name for child in skills_root.iterdir() if (child / "SKILL.md").is_file()
    )
    _require(names == PUBLIC_SKILLS, f"Unexpected public Skill set: {names}")
    for name in names:
        text = (skills_root / name / "SKILL.md").read_text(encoding="utf-8")
        _require(re.search(rf"^name:\s*{re.escape(name)}$", text, re.MULTILINE) is not None, f"Invalid frontmatter for {name}")
        entrypoint = skills_root / name / "scripts" / "run.py"
        _require(entrypoint.is_file(), f"Missing entrypoint for {name}")
        _require(len(entrypoint.read_text(encoding="utf-8").splitlines()) <= 12, f"Entrypoint is not thin: {name}")
    return {"status": "pass", "count": len(names), "names": names}


def audit_manifests(root: Path) -> dict[str, Any]:
    elftia = _load_json(root / "elftia-plugin.json")
    claude = _load_json(root / ".claude-plugin" / "plugin.json")
    _require(elftia.get("kind") == "agent", "Elftia manifest kind must be agent")
    _require(elftia.get("contributes") == {"agent": {"skills": ["./skills"]}}, "Elftia manifest is not discovery-only")
    _require(claude.get("skills") == "./skills/", "Claude manifest Skills root differs")
    forbidden = {"mcp", "hooks", "commands", "subagents", "subAgents", "daemon", "executable", "main"}
    _require(not (_keys(elftia) | _keys(claude)) & forbidden, "Manifest declares forbidden execution integration")
    return {"status": "pass", "skills_root": "skills"}


def audit_commands(root: Path) -> dict[str, Any]:
    return audit_agent_commands(root)


def audit_inventory(root: Path, inventory: list[str] | None = None) -> dict[str, Any]:
    paths = inventory or release_inventory(root)
    for relative in paths:
        identity = PORTABLE_PATH_POLICY.parse_relative(relative)
        _require(
            not identity.has_forbidden_component
            and not {
                PORTABLE_PATH_POLICY.component_key(item)
                for item in FORBIDDEN_NAMES
            }.intersection(identity.keys),
            f"Forbidden release artifact: {relative}",
        )
        _require(
            not is_forbidden_execution_path(relative),
            f"Forbidden execution layer: {relative}",
        )
        _require(not relative.endswith((".pyc", ".pyo")), f"Python cache in release: {relative}")
    artifacts = release_artifacts(root, paths)
    return {
        "status": "pass",
        "file_count": len(paths),
        "risky_count": sum(artifact.risky for artifact in artifacts),
        "classified_count": len(artifacts),
    }


def release_inventory(root: Path) -> list[str]:
    return build_release_inventory(root)


def audit_fixtures(root: Path) -> dict[str, Any]:
    fixture_root = root / "tests" / "fixtures"
    manifest = _load_json(fixture_root / "manifest.json")
    records = {record["path"]: record for record in manifest["fixtures"]}
    binaries = sorted(
        path.relative_to(fixture_root).as_posix()
        for path in fixture_root.rglob("*")
        if path.is_file()
        and path.name not in {"manifest.json", "POLICY.md"}
        and "recipes" not in path.parts
    )
    _require(sorted(records) == binaries, f"Fixture registry mismatch: {binaries}")
    for relative, record in records.items():
        PORTABLE_PATH_POLICY.require_release_safe(
            f"tests/fixtures/{relative}"
        )
        _require(record.get("redistribution_allowed") is True, f"Fixture is not redistributable: {relative}")
        _require(bool(record.get("license")), f"Fixture license missing: {relative}")
        _require(record.get("origin") in {"generated", "public"}, f"Fixture origin invalid: {relative}")
        actual = hashlib.sha256((fixture_root / relative).read_bytes()).hexdigest()
        _require(actual == record.get("sha256"), f"Fixture hash drift: {relative}")
    return {"status": "pass", "fixture_count": len(records)}


def audit_sbom(root: Path) -> dict[str, Any]:
    expected = canonical_json(build_sbom(root))
    actual_path = root / "sbom.cdx.json"
    _require(actual_path.is_file(), "Checked-in CycloneDX SBOM is missing")
    _require(actual_path.read_text(encoding="utf-8") == expected, "Lock/SBOM parity failed")
    notices = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8").lower()
    licenses = _load_json(root / "provenance" / "dependency-licenses.json")
    for package in licenses:
        _require(package.casefold() in notices, f"Dependency notice is missing: {package}")
    return {"status": "pass", "sha256": hashlib.sha256(expected.encode()).hexdigest()}


def _capture(errors: list[dict[str, str]], check: str, callback: Any) -> dict[str, Any]:
    try:
        return callback()
    except (AssertionError, OSError, ValueError, KeyError) as error:
        errors.append({"check": check, "message": str(error)})
        return {"status": "fail"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value), set())
    return set()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_audits(args.project_root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        print(rendered, end="")
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
