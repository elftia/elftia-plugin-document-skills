"""Structural audit for forbidden MCP and execution-adapter surfaces."""

import json
from pathlib import Path
import re
import tomllib
from typing import Any

from .audit_python import MCP_PYTHON_PACKAGES, audit_python_source
from .audit_node import audit_node_source, is_runtime_node
from .release_inventory import (
    release_artifacts,
    release_inventory,
)
from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY
from .supply_chain import build_sbom, nuget_graph

_SOURCE_SUFFIXES = {".cjs", ".js", ".jsx", ".mjs", ".mts", ".py", ".ts", ".tsx"}
_NODE_PACKAGES = {
    "@modelcontextprotocol/sdk",
    "fastmcp",
    "mcp-framework",
}
_PATH_TOKENS = {
    "adapter",
    "adapters",
    "daemon",
    "daemons",
    "hook",
    "hooks",
    "mcp",
    "mcpserver",
    "mcpservers",
    "mcptransport",
    "server",
    "servers",
    "transport",
    "transports",
}
_NODE_API = re.compile(
    r"(?x)"
    r"@modelcontextprotocol/sdk|"
    r"\b(?:FastMCP|McpServer|StdioServerTransport|SSEServerTransport)\b|"
    r"\.(?:registerTool|setRequestHandler)\s*\(|"
    r"\bserver\.(?:tool|resource|prompt)\s*\("
)


def audit_execution_boundary(
    root: Path, inventory: list[str] | None = None
) -> dict[str, Any]:
    release_paths = inventory if inventory is not None else release_inventory(root)
    shared_inventory = release_artifacts(root, release_paths)
    artifacts = [artifact.path for artifact in shared_inventory if artifact.risky]
    for relative in artifacts:
        _require(
            not is_forbidden_execution_path(relative),
            f"Forbidden execution-layer path: {relative}",
        )
    inspected = 0
    for path in _release_sources(root, artifacts):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix == ".py":
            audit_python_source(relative, text)
        else:
            audit_node_source(root, relative, text)
            if is_runtime_node(relative):
                _require(
                    _NODE_API.search(text) is None,
                    f"Forbidden MCP SDK or registration API in {relative}",
                )
        inspected += 1
    dependency_manifests = _audit_dependency_manifests(root)
    _audit_exact_allowlists(root)
    _audit_registration_manifests(root)
    return {
        "status": "pass",
        "source_files": inspected,
        "executable_artifacts": len(artifacts),
        "classified_release_files": len(shared_inventory),
        "dependency_manifests": dependency_manifests,
        "registration_manifests": 2,
    }


def runtime_source_allowlist(root: Path) -> dict[str, list[str]]:
    """Return the exact distributable runtime sources covered by value-flow policy."""
    sources: dict[str, list[str]] = {}
    sources["python"] = sorted(
        path.relative_to(root).as_posix()
        for base in ("src", "skills", "providers", "runtime")
        if (root / base).exists()
        for path in (root / base).rglob("*.py")
        if path.is_file()
    )
    sources["node"] = sorted(
        path.relative_to(root).as_posix()
        for base in ("src", "skills", "providers", "runtime")
        if (root / base).exists()
        for path in (root / base).rglob("*")
        if path.is_file() and path.suffix.lower() in {".js", ".mjs", ".cjs", ".ts"}
    )
    return sources


def is_forbidden_execution_path(relative: str) -> bool:
    identity = PORTABLE_PATH_POLICY.parse_relative(relative)
    if identity.has_forbidden_component:
        return True
    for part in identity.keys:
        normalized = re.sub(r"[^a-z0-9]", "", Path(part).stem.casefold())
        if normalized in _PATH_TOKENS or normalized.startswith("mcp"):
            return True
    return False


def _release_sources(root: Path, artifacts: list[str]) -> list[Path]:
    return sorted(
        root / relative
        for relative in artifacts
        if Path(relative).suffix.lower() in _SOURCE_SUFFIXES
    )


def _audit_dependency_manifests(root: Path) -> int:
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    node_names = {
        name.lower()
        for section in ("dependencies", "devDependencies", "optionalDependencies")
        for name in package.get(section, {})
    }
    _require(
        not any(_is_mcp_package(name) for name in node_names),
        "package.json declares an MCP dependency",
    )
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    dependency_strings = list(project.get("project", {}).get("dependencies", []))
    dependency_strings.extend(
        dependency
        for group in project.get("project", {})
        .get("optional-dependencies", {})
        .values()
        for dependency in group
    )
    dependency_strings.extend(
        dependency
        for group in project.get("dependency-groups", {}).values()
        for dependency in group
    )
    python_names = {
        re.split(r"[\s\[<>=!~]", dependency, maxsplit=1)[0].lower()
        for dependency in dependency_strings
    }
    _require(
        not any(_is_mcp_package(name) for name in python_names),
        "pyproject.toml declares an MCP dependency",
    )
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    locked_names = {item["name"].lower() for item in lock.get("package", [])}
    _require(
        not any(_is_mcp_package(name) for name in locked_names),
        "uv.lock contains an MCP dependency",
    )
    node_lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    locked_node_names = {
        (package.get("name") or path.rsplit("node_modules/", 1)[-1]).lower()
        for path, package in node_lock.get("packages", {}).items()
        if path
    }
    _require(
        not any(_is_mcp_package(name) for name in locked_node_names),
        "package-lock.json contains an MCP dependency",
    )
    helper_root = (
        root / "src" / "document_skills_core" / "providers" / "dotnet" / "helper"
    )
    nuget_project = helper_root / "OpenXmlHelper.csproj"
    nuget_lock = helper_root / "packages.lock.json"
    present = (nuget_project.is_file(), nuget_lock.is_file())
    _require(
        present in {(False, False), (True, True)},
        "NuGet helper project and dependency lock must be present together",
    )
    if present == (True, True):
        components, dependencies = nuget_graph(root)
        policy = json.loads(
            (root / "provenance" / "dependency-allowlist.json").read_text(
                encoding="utf-8"
            )
        )["nuget"]
        references = {
            component["bom-ref"]: component["name"] for component in components
        }
        packages = {component["name"]: component["version"] for component in components}
        hashes = {
            component["name"]: component["hashes"][0]["content"]
            for component in components
        }
        edges = {
            references[dependency["ref"]]: [
                references[target] for target in dependency["dependsOn"]
            ]
            for dependency in dependencies
            if dependency["ref"] != "application:document-skills"
        }
        _require(
            packages == policy["packages"],
            "Frozen NuGet production graph differs from the exact allowlist",
        )
        _require(
            hashes == policy["sha512"],
            "Frozen NuGet content hashes differ from the exact allowlist",
        )
        _require(
            edges == policy["dependencies"],
            "Frozen NuGet dependency edges differ from the exact allowlist",
        )
        return 6
    return 4


def _audit_registration_manifests(root: Path) -> None:
    for path in (root / "elftia-plugin.json", root / ".claude-plugin" / "plugin.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key, value in _walk_json(payload):
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            _require(
                normalized not in {"mcp", "mcpserver", "mcpservers", "mcptransport"},
                f"Manifest declares MCP registration: {path.name}:{key}",
            )
            if isinstance(value, str):
                lowered = value.lower()
                _require(
                    not any(package in lowered for package in _NODE_PACKAGES),
                    f"Manifest references MCP runtime: {path.name}:{key}",
                )


def _audit_exact_allowlists(root: Path) -> None:
    dependency_policy_path = root / "provenance" / "dependency-allowlist.json"
    runtime_policy_path = root / "provenance" / "runtime-source-allowlist.json"
    present = (dependency_policy_path.is_file(), runtime_policy_path.is_file())
    _require(
        present in {(False, False), (True, True)},
        "Exact dependency and runtime-source allowlists must be present together",
    )
    if present == (False, False):
        # Small structural unit fixtures deliberately omit release policy files.
        # Complete release roots always carry both files and take the strict path.
        return
    policy = json.loads(dependency_policy_path.read_text(encoding="utf-8"))
    sbom = build_sbom(root)
    actual: dict[str, dict[str, str]] = {
        "python": {},
        "node": {},
        "nuget": {},
    }
    for component in sbom["components"]:
        purl = component.get("purl", "")
        if purl.startswith("pkg:pypi/"):
            actual["python"][component["name"]] = component["version"]
        elif purl.startswith("pkg:npm/"):
            actual["node"][component["name"]] = component["version"]
        elif purl.startswith("pkg:nuget/"):
            actual["nuget"][component["name"]] = component["version"]
    _require(
        actual["python"] == policy["python"]["packages"],
        "Frozen Python production graph differs from the exact allowlist",
    )
    _require(
        actual["node"] == policy["node"]["packages"],
        "Frozen Node production graph differs from the exact allowlist",
    )
    _require(
        actual["nuget"] == policy["nuget"]["packages"],
        "Frozen NuGet production graph differs from the exact allowlist",
    )
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    locked = {_normalize_python_name(item["name"]): item for item in lock["package"]}
    direct_dev = {
        _normalize_python_name(re.split(r"[\s\[<>=!~]", item, maxsplit=1)[0])
        for group in project.get("dependency-groups", {}).values()
        for item in group
    }
    selected_dev: set[str] = set()
    pending = list(direct_dev)
    while pending:
        name = pending.pop()
        if name in selected_dev or name not in locked:
            continue
        selected_dev.add(name)
        pending.extend(
            _normalize_python_name(item["name"])
            for item in locked[name].get("dependencies", [])
        )
    development_graph = {
        name: locked[name]["version"]
        for name in sorted(selected_dev - set(actual["python"]))
    }
    _require(
        development_graph == policy["python"]["development_packages"],
        "Frozen Python development graph differs from the exact allowlist",
    )
    runtime_policy = json.loads(runtime_policy_path.read_text(encoding="utf-8"))
    actual_sources = runtime_source_allowlist(root)
    _require(
        actual_sources["python"] == runtime_policy["python"],
        "Python runtime-source allowlist differs from exact current files",
    )
    _require(
        actual_sources["node"] == runtime_policy["node"],
        "Node runtime-source allowlist differs from exact current files",
    )


def _normalize_python_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def _walk_json(value: Any, key: str = "$") -> list[tuple[str, Any]]:
    items = [(key, value)]
    if isinstance(value, dict):
        for child_key, child in value.items():
            items.extend(_walk_json(child, str(child_key)))
    elif isinstance(value, list):
        for child in value:
            items.extend(_walk_json(child, key))
    return items


def _is_mcp_package(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered in MCP_PYTHON_PACKAGES | _NODE_PACKAGES
        or lowered.startswith(("mcp-", "@modelcontextprotocol/"))
        or "fastmcp" in lowered
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
