"""Exercise every Core DOCX operation through the public frozen facade for CI."""

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from document_skills_core.core.contracts.schemas import SchemaCatalog

CORE_OPERATIONS = frozenset(
    {
        "docx.read",
        "docx.inspect.accessibility",
        "docx.inspect.structure",
        "docx.compare.semantic",
        "docx.create",
        "docx.edit",
        "docx.edit.replace-text",
        "docx.merge",
        "docx.template.apply",
    }
)
OPTIONAL_PROVIDERS = frozenset({"libreoffice", "dotnet-openxml"})


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    evidence_root = Path(sys.argv[1]).resolve()
    evidence_root.mkdir(parents=True, exist_ok=True)
    catalog = SchemaCatalog(project_root)

    doctor = _command(project_root, "doctor", "--json")
    catalog.validate("doctor-report", doctor)
    _write_json(evidence_root / "doctor.json", doctor)
    capabilities = _command(project_root, "capabilities", "--json")
    catalog.validate("capability-report", capabilities)
    _write_json(evidence_root / "capabilities.json", capabilities)
    _assert_core_only_profile(doctor, capabilities)

    created = evidence_root / "created.docx"
    appendix = evidence_root / "appendix.docx"
    results: dict[str, dict[str, Any]] = {}
    results["docx.create"] = _run(
        project_root,
        evidence_root,
        catalog,
        "create",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(created),
            "arguments": {
                "report": {
                    "metadata": {"title": "DOCX Core CI"},
                    "blocks": [
                        {"type": "heading", "text": "DOCX Core CI", "level": 1},
                        {"type": "paragraph", "text": "Hello {name}"},
                        {"type": "paragraph", "text": "REPLACE ME"},
                    ],
                }
            },
        },
        "core-python",
    )
    _run(
        project_root,
        evidence_root,
        catalog,
        "appendix-create",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(appendix),
            "arguments": {
                "report": {
                    "metadata": {"title": "DOCX Core CI Appendix"},
                    "blocks": [
                        {"type": "heading", "text": "Appendix", "level": 1},
                        {"type": "paragraph", "text": "Portable evidence"},
                    ],
                }
            },
        },
        "core-python",
    )

    read_only = {
        "docx.read": {},
        "docx.inspect.accessibility": {},
        "docx.inspect.structure": {},
        "docx.compare.semantic": {
            "baseline": str(created),
            "expected_baseline_sha256": _sha256(created),
            "allowed_changes": [],
        },
    }
    for operation, arguments in read_only.items():
        results[operation] = _run(
            project_root,
            evidence_root,
            catalog,
            operation.removeprefix("docx.").replace(".", "-"),
            {
                "schema_version": "1.0",
                "operation": operation,
                "input": str(created),
                "arguments": arguments,
            },
            "core-python",
        )

    mutations = {
        "docx.edit": (
            "edited.docx",
            {
                "edits": [
                    {
                        "type": "paragraph_style",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "Hello {name}",
                        },
                        "style": "Heading2",
                    }
                ]
            },
            "core-python",
        ),
        "docx.edit.replace-text": (
            "replaced.docx",
            {
                "replacements": [
                    {
                        "search": "REPLACE ME",
                        "replace": "REPLACED",
                        "expected_matches": 1,
                    }
                ]
            },
            "core-python",
        ),
        "docx.template.apply": (
            "templated.docx",
            {"variables": {"name": "Agent"}},
            "core-node",
        ),
        "docx.merge": (
            "merged.docx",
            {
                "sources": [
                    {"path": str(appendix), "expected_sha256": _sha256(appendix)}
                ],
                "style_conflict_policy": "require-identical",
                "numbering_conflict_policy": "require-identical",
            },
            "core-python",
        ),
    }
    for operation, (output_name, arguments, provider) in mutations.items():
        results[operation] = _run(
            project_root,
            evidence_root,
            catalog,
            operation.removeprefix("docx.").replace(".", "-"),
            {
                "schema_version": "1.0",
                "operation": operation,
                "input": str(created),
                "output": str(evidence_root / output_name),
                "arguments": arguments,
            },
            provider,
        )

    if set(results) != CORE_OPERATIONS:
        raise AssertionError(f"Core operation evidence is incomplete: {sorted(results)}")
    index = {
        "schema_version": "1.0",
        "provider_profile": "core-only",
        "operations": [
            {
                "operation": operation,
                "status": result["status"],
                "provider_chain": result["provider_chain"],
                "result": f"result-{operation.removeprefix('docx.').replace('.', '-')}.json",
            }
            for operation, result in sorted(results.items())
        ],
    }
    _write_json(evidence_root / "evidence-index.json", index)
    return 0


def _assert_core_only_profile(
    doctor: dict[str, Any],
    capabilities: dict[str, Any],
) -> None:
    doctor_states = {item["id"]: item for item in doctor["providers"]}
    capability_states = {item["id"]: item for item in capabilities["providers"]}
    for provider_id in OPTIONAL_PROVIDERS:
        for states in (doctor_states, capability_states):
            state = states[provider_id]
            if state["available"] is not False or "core-only" not in state["reason"]:
                raise AssertionError(f"Optional provider was not disabled: {state}")
    available = {
        item["operation"]
        for item in capabilities["operations"]
        if item["available"] is True
    }
    if available != CORE_OPERATIONS:
        raise AssertionError(f"Unexpected Core-only DOCX surface: {sorted(available)}")


def _run(
    project_root: Path,
    evidence_root: Path,
    catalog: SchemaCatalog,
    slug: str,
    request: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    request_path = evidence_root / f"request-{slug}.json"
    result_path = evidence_root / f"result-{slug}.json"
    _write_json(request_path, request)
    result = _command(project_root, "run", "--request", str(request_path))
    catalog.validate("operation-result", result)
    if result["status"] != "success" or result["provider_chain"] != [provider]:
        raise AssertionError(f"Unexpected {request['operation']} result: {result}")
    _write_json(result_path, result)
    return result


def _command(project_root: Path, *arguments: str) -> dict[str, Any]:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is unavailable")
    completed = subprocess.run(
        [
            uv,
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-docx/scripts/run.py"),
            *arguments,
        ],
        cwd=project_root,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0 or completed.stderr:
        raise RuntimeError(
            f"Public DOCX command failed ({completed.returncode}): "
            f"{completed.stderr.decode('utf-8', errors='replace')}"
        )
    value = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    if type(value) is not dict:
        raise TypeError("Public DOCX command returned a non-object result")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
