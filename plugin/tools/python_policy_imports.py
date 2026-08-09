"""Exact import allowlisting for distributable Python runtime sources."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Protocol

from .python_policy_definitions import (
    ALLOWED_STDLIB,
    DANGEROUS_ATTRIBUTES,
    DANGEROUS_BUILTINS,
    DANGEROUS_MODULES,
    MCP_PYTHON_PACKAGES,
)
from .python_policy_flow import AbstractValue


class _ImportHost(Protocol):
    relative: str
    scopes: list[dict[str, AbstractValue]]

    @staticmethod
    def _require(condition: object, message: str) -> None: ...


def bind_imports(host: _ImportHost, statement: ast.Import | ast.ImportFrom) -> None:
    if isinstance(statement, ast.Import):
        imports = [
            (alias.name, alias.asname or alias.name.split(".")[0])
            for alias in statement.names
        ]
    else:
        module = statement.module or ""
        imports = [
            (f"{module}.{alias.name}", alias.asname or alias.name)
            for alias in statement.names
        ]
    for qualified, local in imports:
        root = qualified.split(".", 1)[0]
        normalized = root.casefold()
        host._require(
            normalized not in DANGEROUS_MODULES,
            f"Dynamic loader/reflection module is forbidden: {host.relative}:{root}",
        )
        host._require(
            normalized not in MCP_PYTHON_PACKAGES,
            f"Forbidden MCP Python import: {host.relative}:{root}",
        )
        if not (isinstance(statement, ast.ImportFrom) and statement.level > 0):
            _require_allowed_import(host, root)
        terminal = qualified.rsplit(".", 1)[-1]
        host._require(
            terminal not in DANGEROUS_ATTRIBUTES
            and terminal not in DANGEROUS_BUILTINS,
            f"Dangerous loader/reflection identity imported: "
            f"{host.relative}:{terminal}",
        )
        host.scopes[-1][local] = (
            f"module:{root}" if "." not in qualified else "safe"
        )


def reject_static_mcp_imports(relative: str, tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = (node.module,)
        else:
            continue
        for name in names:
            if name.split(".", 1)[0].casefold() in MCP_PYTHON_PACKAGES:
                raise AssertionError(f"Forbidden MCP Python import in {relative}")


def _require_allowed_import(host: _ImportHost, root: str) -> None:
    if root == "document_skills_core" or root in ALLOWED_STDLIB:
        return
    path = Path(__file__).resolve().parents[1] / "provenance"
    allowlist = json.loads(
        (path / "dependency-allowlist.json").read_text(encoding="utf-8")
    )
    host._require(
        root in set(allowlist["python"]["import_roots"]),
        f"Python runtime import is not in the exact allowlist: "
        f"{host.relative}:{root}",
    )
