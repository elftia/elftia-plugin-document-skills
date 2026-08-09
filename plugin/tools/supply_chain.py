"""Deterministic CycloneDX generation from frozen Python/Node graphs."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any

from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

from .release_inventory import release_inventory

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+")


def build_sbom(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    for relative in release_inventory(root):
        try:
            PORTABLE_PATH_POLICY.require_release_safe(relative)
        except ValueError as error:
            raise ValueError(
                f"Forbidden release path cannot enter SBOM scope: {relative}"
            ) from error
    python_components, python_dependencies = _python_graph(root)
    node_components, node_dependencies = _node_graph(root)
    provenance = _load_json(root / "provenance" / "modules.json")
    adopted = [
        {
            "type": "file",
            "name": record["module"],
            "bom-ref": f"adopted:{record['module']}",
            "licenses": [{"license": {"id": record["license"]}}],
            "properties": [{"name": "elftia:source-class", "value": "adopted"}],
        }
        for record in provenance.get("adopted_sources", [])
    ]
    provider_files = [
        _provider_component(root, "runtime/node/health.mjs", "core-node-health"),
        _provider_component(
            root,
            "runtime/node/docx_template.mjs",
            "core-node-docx-template",
        ),
        _provider_component(
            root,
            "runtime/node/html_capture.mjs",
            "html-browser-capture",
        ),
    ]
    components = sorted(
        [*python_components, *node_components, *adopted, *provider_files],
        key=lambda item: item["bom-ref"],
    )
    dependency_map: dict[str, set[str]] = {}
    for dependency in [*python_dependencies, *node_dependencies]:
        dependency_map.setdefault(dependency["ref"], set()).update(dependency["dependsOn"])
    dependencies = [
        {"ref": reference, "dependsOn": sorted(targets)}
        for reference, targets in sorted(dependency_map.items())
    ]
    revision = hashlib.sha256(
        (root / "uv.lock").read_bytes() + (root / "package-lock.json").read_bytes()
    ).hexdigest()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{revision[:8]}-{revision[8:12]}-{revision[12:16]}-{revision[16:20]}-{revision[20:32]}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "document-skills",
                "version": "0.1.0",
                "bom-ref": "application:document-skills",
            },
            "properties": [{"name": "elftia:lock-sha256", "value": revision}],
        },
        "components": components,
        "dependencies": dependencies,
    }


def _python_graph(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    packages = {_normalize(item["name"]): item for item in lock["package"]}
    direct = {
        _normalize(_NAME_PATTERN.match(item).group(0))
        for item in project["project"].get("dependencies", [])
    }
    selected: set[str] = set()
    pending = list(direct)
    while pending:
        name = pending.pop()
        if name in selected or name not in packages:
            continue
        selected.add(name)
        pending.extend(
            _normalize(dependency["name"])
            for dependency in packages[name].get("dependencies", [])
        )
    licenses = _load_json(root / "provenance" / "dependency-licenses.json")
    missing = sorted(name for name in selected if name not in licenses)
    if missing:
        raise ValueError(f"Missing dependency license records: {missing}")
    components = []
    dependencies = []
    for name in sorted(selected):
        package = packages[name]
        reference = f"pkg:pypi/{name}@{package['version']}"
        components.append(
            {
                "type": "library",
                "name": name,
                "version": package["version"],
                "bom-ref": reference,
                "purl": reference,
                "licenses": [{"license": {"id": licenses[name]}}],
            }
        )
        targets = [
            f"pkg:pypi/{dependency_name}@{packages[dependency_name]['version']}"
            for dependency_name in sorted(
                {
                    _normalize(item["name"])
                    for item in package.get("dependencies", [])
                    if _normalize(item["name"]) in selected
                }
            )
        ]
        dependencies.append({"ref": reference, "dependsOn": targets})
    dependencies.append(
        {
            "ref": "application:document-skills",
            "dependsOn": [
                f"pkg:pypi/{name}@{packages[name]['version']}" for name in sorted(direct)
            ],
        }
    )
    return components, dependencies


def _node_graph(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lock = _load_json(root / "package-lock.json")
    licenses = _load_json(root / "provenance" / "dependency-licenses.json")
    components = []
    root_dependencies = lock["packages"][""].get("dependencies", {})
    packages_by_name = {
        package.get("name") or path.removeprefix("node_modules/"): package
        for path, package in lock["packages"].items()
        if path and not package.get("dev")
    }
    missing = sorted(set(packages_by_name) - set(licenses))
    if missing:
        raise ValueError(f"Missing dependency license records: {missing}")
    dependencies = []
    for path, package in sorted(lock["packages"].items()):
        if not path or package.get("dev"):
            continue
        name = package.get("name") or path.removeprefix("node_modules/")
        version = package["version"]
        reference = f"pkg:npm/{name}@{version}"
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "bom-ref": reference,
                "purl": reference,
                "licenses": [{"license": {"id": licenses[name]}}],
            }
        )
        dependencies.append(
            {
                "ref": reference,
                "dependsOn": [
                    _node_reference(dependency_name, packages_by_name)
                    for dependency_name in sorted(package.get("dependencies", {}))
                ],
            }
        )
    depends_on = [
        _node_reference(name, packages_by_name)
        for name in sorted(root_dependencies)
    ]
    dependencies.append(
        {"ref": "application:document-skills", "dependsOn": depends_on}
    )
    return components, dependencies


def _node_reference(
    name: str,
    packages_by_name: dict[str, dict[str, Any]],
) -> str:
    package = packages_by_name.get(name)
    if package is None:
        raise ValueError(f"Node lock does not resolve dependency: {name}")
    return f"pkg:npm/{name}@{package['version']}"


def _provider_component(root: Path, path: str, identity: str) -> dict[str, Any]:
    return {
        "type": "file",
        "name": path,
        "bom-ref": f"provider:{identity}",
        "hashes": [
            {
                "alg": "SHA-256",
                "content": _sha256(root / path),
            }
        ],
        "licenses": [{"license": {"id": "GPL-3.0"}}],
        "properties": [{"name": "elftia:provider", "value": "core-node"}],
    }


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = canonical_json(build_sbom(args.project_root))
    if args.output:
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
