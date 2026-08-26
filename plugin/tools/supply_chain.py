"""Deterministic CycloneDX generation from frozen Python/Node/NuGet graphs."""

import argparse
import base64
import binascii
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any
from xml.etree import ElementTree

from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

from .release_inventory import release_inventory

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+")
_NUGET_HELPER_ROOT = Path("src/document_skills_core/providers/dotnet/helper")
_NUGET_PROJECT_NAME = "OpenXmlHelper.csproj"
_NUGET_LOCK_NAME = "packages.lock.json"


def build_sbom(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = project["project"]["version"]
    for relative in release_inventory(root):
        try:
            PORTABLE_PATH_POLICY.require_release_safe(relative)
        except ValueError as error:
            raise ValueError(
                f"Forbidden release path cannot enter SBOM scope: {relative}"
            ) from error
    python_components, python_dependencies = _python_graph(root)
    node_components, node_dependencies = _node_graph(root)
    nuget_components, nuget_dependencies = nuget_graph(root)
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
        [
            *python_components,
            *node_components,
            *nuget_components,
            *adopted,
            *provider_files,
        ],
        key=lambda item: item["bom-ref"],
    )
    dependency_map: dict[str, set[str]] = {}
    for dependency in [
        *python_dependencies,
        *node_dependencies,
        *nuget_dependencies,
    ]:
        dependency_map.setdefault(dependency["ref"], set()).update(
            dependency["dependsOn"]
        )
    dependencies = [
        {"ref": reference, "dependsOn": sorted(targets)}
        for reference, targets in sorted(dependency_map.items())
    ]
    revision = hashlib.sha256(
        b"uv.lock\0"
        + (root / "uv.lock").read_bytes()
        + b"\0package-lock.json\0"
        + (root / "package-lock.json").read_bytes()
        + b"\0packages.lock.json\0"
        + (root / _NUGET_HELPER_ROOT / _NUGET_LOCK_NAME).read_bytes()
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
                "version": project_version,
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
                f"pkg:pypi/{name}@{packages[name]['version']}"
                for name in sorted(direct)
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
        _node_reference(name, packages_by_name) for name in sorted(root_dependencies)
    ]
    dependencies.append({"ref": "application:document-skills", "dependsOn": depends_on})
    return components, dependencies


def _node_reference(
    name: str,
    packages_by_name: dict[str, dict[str, Any]],
) -> str:
    package = packages_by_name.get(name)
    if package is None:
        raise ValueError(f"Node lock does not resolve dependency: {name}")
    return f"pkg:npm/{name}@{package['version']}"


def nuget_graph(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the exact NuGet graph after validating project/lock parity."""
    helper_root = root / _NUGET_HELPER_ROOT
    project_path = helper_root / _NUGET_PROJECT_NAME
    lock_path = helper_root / _NUGET_LOCK_NAME
    if not project_path.is_file():
        raise ValueError(
            f"NuGet helper project is missing: {_NUGET_HELPER_ROOT / _NUGET_PROJECT_NAME}"
        )
    if not lock_path.is_file():
        raise ValueError(
            f"NuGet dependency lock is missing: {_NUGET_HELPER_ROOT / _NUGET_LOCK_NAME}"
        )

    framework, direct = _nuget_project(project_path)
    lock = _load_json(lock_path)
    if lock.get("version") != 1:
        raise ValueError("Unsupported NuGet packages.lock.json version")
    target_graphs = lock.get("dependencies")
    if not isinstance(target_graphs, dict) or set(target_graphs) != {framework}:
        raise ValueError("NuGet lock target framework differs from the helper project")
    packages = target_graphs[framework]
    if not isinstance(packages, dict) or not packages:
        raise ValueError("NuGet lock contains no packages")

    locked_direct = {
        name
        for name, package in packages.items()
        if isinstance(package, dict) and package.get("type") == "Direct"
    }
    if locked_direct != set(direct):
        raise ValueError(
            "NuGet direct dependency graph differs from the helper project"
        )

    licenses = _load_json(root / "provenance" / "dependency-licenses.json")
    missing_licenses = sorted(set(packages) - set(licenses))
    if missing_licenses:
        raise ValueError(f"Missing dependency license records: {missing_licenses}")

    resolved_versions: dict[str, str] = {}
    edges: dict[str, set[str]] = {}
    component_hashes: dict[str, str] = {}
    for name, package in packages.items():
        if not isinstance(name, str) or not isinstance(package, dict):
            raise ValueError("NuGet lock contains a malformed package record")
        dependency_type = package.get("type")
        expected_type = "Direct" if name in direct else "Transitive"
        if dependency_type != expected_type:
            raise ValueError(f"NuGet dependency type drifted for {name}")
        resolved = package.get("resolved")
        if not isinstance(resolved, str) or not resolved:
            raise ValueError(f"NuGet resolved version is invalid for {name}")
        resolved_versions[name] = resolved
        content_hash = package.get("contentHash")
        if not isinstance(content_hash, str):
            raise ValueError(f"NuGet content hash is missing for {name}")
        try:
            raw_hash = base64.b64decode(content_hash, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError(f"NuGet content hash is invalid for {name}") from error
        if len(raw_hash) != 64:
            raise ValueError(f"NuGet content hash is not SHA-512 for {name}")
        component_hashes[name] = raw_hash.hex()
        raw_dependencies = package.get("dependencies", {})
        if not isinstance(raw_dependencies, dict):
            raise ValueError(f"NuGet dependency edges are invalid for {name}")
        edges[name] = set(raw_dependencies)

    for name, version in direct.items():
        record = packages[name]
        requested = record.get("requested")
        if _exact_nuget_version(requested) != version:
            raise ValueError(f"NuGet requested version drifted for {name}")
        if resolved_versions[name] != version:
            raise ValueError(f"NuGet resolved version drifted for {name}")

    for name, targets in edges.items():
        record_dependencies = packages[name].get("dependencies", {})
        for target in targets:
            if target not in packages:
                raise ValueError(f"NuGet lock does not resolve dependency: {target}")
            constraint = record_dependencies[target]
            if constraint != resolved_versions[target]:
                raise ValueError(
                    f"NuGet dependency edge version drifted: {name} -> {target}"
                )

    reachable: set[str] = set()
    pending = list(direct)
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        pending.extend(edges[name])
    if reachable != set(packages):
        raise ValueError("NuGet lock contains packages outside the reachable graph")

    components = []
    dependencies = []
    for name in sorted(packages):
        version = resolved_versions[name]
        reference = _nuget_reference(name, version)
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "bom-ref": reference,
                "purl": reference,
                "hashes": [{"alg": "SHA-512", "content": component_hashes[name]}],
                "licenses": [{"license": {"id": licenses[name]}}],
                "properties": [
                    {
                        "name": "elftia:nuget-dependency-type",
                        "value": packages[name]["type"].lower(),
                    }
                ],
            }
        )
        dependencies.append(
            {
                "ref": reference,
                "dependsOn": [
                    _nuget_reference(target, resolved_versions[target])
                    for target in sorted(edges[name])
                ],
            }
        )
    dependencies.append(
        {
            "ref": "application:document-skills",
            "dependsOn": [
                _nuget_reference(name, resolved_versions[name])
                for name in sorted(direct)
            ],
        }
    )
    return components, dependencies


def _nuget_project(project_path: Path) -> tuple[str, dict[str, str]]:
    try:
        project = ElementTree.parse(project_path).getroot()
    except (ElementTree.ParseError, OSError) as error:
        raise ValueError("NuGet helper project is not valid XML") from error
    properties: dict[str, list[str]] = {}
    for group in project:
        if _xml_local_name(group.tag) != "PropertyGroup":
            continue
        for element in group:
            properties.setdefault(_xml_local_name(element.tag), []).append(
                (element.text or "").strip()
            )
    if [value.casefold() for value in properties.get("RestorePackagesWithLockFile", [])] != [
        "true"
    ]:
        raise ValueError("NuGet helper project does not require a lock file")
    if [value.casefold() for value in properties.get("RestoreLockedMode", [])] != [
        "true"
    ]:
        raise ValueError("NuGet helper project does not enforce locked restore")
    frameworks = properties.get("TargetFramework", [])
    if len(frameworks) != 1 or not frameworks[0]:
        raise ValueError("NuGet helper project target framework is missing or ambiguous")
    framework = frameworks[0]

    direct: dict[str, str] = {}
    for reference in project.iter():
        if _xml_local_name(reference.tag) != "PackageReference":
            continue
        name = reference.get("Include")
        specification = reference.get("Version")
        if specification is None:
            version_element = next(
                (
                    child
                    for child in reference
                    if _xml_local_name(child.tag) == "Version"
                ),
                None,
            )
            specification = (
                (version_element.text or "").strip()
                if version_element is not None
                else None
            )
        if not name or name in direct:
            raise ValueError("NuGet helper project has an invalid PackageReference")
        direct[name] = _exact_nuget_version(specification)
    if not direct:
        raise ValueError("NuGet helper project declares no PackageReference")
    return framework, direct


def _exact_nuget_version(specification: object) -> str:
    if not isinstance(specification, str):
        raise ValueError("NuGet dependency is not exact-version pinned")
    match = re.fullmatch(r"\[([^,\]\s]+)\]", specification)
    if match:
        return match.group(1)
    match = re.fullmatch(r"\[([^,\]\s]+),\s*([^,\]\s]+)\]", specification)
    if match and match.group(1) == match.group(2):
        return match.group(1)
    raise ValueError("NuGet dependency is not exact-version pinned")


def _nuget_reference(name: str, version: str) -> str:
    return f"pkg:nuget/{name}@{version}"


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


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
