"""Typed provider and runtime catalog contracts."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProviderId(StrEnum):
    CORE_PYTHON = "core-python"
    CORE_NODE = "core-node"
    HTML_BROWSER = "html-browser"
    LIBREOFFICE = "libreoffice"
    DOTNET_OPENXML = "dotnet-openxml"


class RuntimeComponentId(StrEnum):
    UV = "uv"
    PYTHON_LOCK = "python-lock"
    NODE = "node"
    NODE_LOCK = "node-lock"
    DOTNET_RUNTIME = "dotnet-runtime"


@dataclass(frozen=True)
class DetectionEvidence:
    available: bool
    version: str | None = None
    reason: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class ProviderState:
    id: ProviderId | str
    required: bool
    evidence: DetectionEvidence

    def as_record(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "available": self.evidence.available,
            "version": self.evidence.version,
            "reason": self.evidence.reason,
            "required": self.required,
            "path": self.evidence.path,
        }


@dataclass(frozen=True)
class Capability:
    operation: str
    fidelity: str
    semantic_equivalence: bool = True
    validation_strength: int = 0


@dataclass(frozen=True)
class OperationBinding:
    operation: str
    provider_id: ProviderId | str
    capability: Capability
    execute: Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass
class ProviderDefinition:
    id: ProviderId | str
    version: str | None
    detect: Callable[[], DetectionEvidence | dict[str, Any]]
    execute: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
    diagnostics: Callable[[], dict[str, Any]] = field(default=lambda: {})
    capabilities: list[Capability] = field(default_factory=list)
    validators: dict[str, Callable[[], Any]] = field(default_factory=dict)
    startup_cost: int = 0
    risk: int = 0
    required: bool = False
