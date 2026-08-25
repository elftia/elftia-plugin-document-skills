"""Doctor and operation-level capability report assembly."""

from pathlib import Path
from typing import Any

from document_skills_core import __version__

from ..contracts.errors import DocumentSkillsError
from .detectors import RuntimeDetectors
from .provider_state import normalize_detector_records, unavailable_detector_state
from .registry import Provider, ProviderRegistry


def build_doctor(project_root: Path, format_id: str) -> dict[str, Any]:
    states = normalize_detector_records(RuntimeDetectors(project_root).all())
    runtime = states
    from document_skills_core.providers import build_default_registry

    provider_catalog = build_default_registry(project_root)
    providers = [
        _safe_provider_state(provider_catalog, provider)
        for provider in provider_catalog.providers.values()
    ]
    required_failures = [
        state
        for state in [*runtime, *providers]
        if state["required"] and not state["available"]
    ]
    return {
        "schema_version": "1.0",
        "status": "unavailable" if required_failures else "healthy",
        "project_version": __version__,
        "format": format_id,
        "runtime": runtime,
        "providers": providers,
        "errors": [
            {
                "code": "DS_RUNTIME_UNAVAILABLE",
                "component": state["id"],
                "message": state["reason"],
            }
            for state in required_failures
        ],
    }


def build_capabilities(
    project_root: Path, format_id: str, registry: ProviderRegistry
) -> dict[str, Any]:
    provider_states = {
        provider_id: _safe_provider_state(registry, provider)
        for provider_id, provider in registry.providers.items()
    }
    operations = []
    for operation, registrations in sorted(registry.operations.items()):
        if not operation.startswith(f"{format_id}."):
            continue
        available = [
            registration
            for registration in registrations
            if provider_states[str(registration.provider_id)]["available"] is True
            and callable(registration.execute)
        ]
        best = max(
            available,
            key=lambda item: {"core": 0, "enhanced": 1, "full": 2}[item.capability.fidelity],
            default=None,
        )
        operations.append(
            {
                "operation": operation,
                "available": best is not None,
                "fidelity": best.capability.fidelity if best else "none",
                "providers": [str(item.provider_id) for item in available],
                "reason": None if best else "No accepted provider implementation is available.",
            }
        )
    validation_operations = {
        "schema": f"{format_id}.validate.schema",
        "visual": f"{format_id}.render",
    }
    validators = {
        validator_id
        for provider_id, provider in registry.providers.items()
        if provider_states[provider_id]["available"]
        for validator_id, validator in provider.validators.items()
        if callable(validator)
        and any(
            str(registration.provider_id) == provider_id
            and callable(registration.execute)
            for registration in registry.operations.get(
                validation_operations.get(validator_id, ""), []
            )
        )
    }
    return {
        "schema_version": "1.0",
        "format": format_id,
        "operations": operations,
        "providers": list(provider_states.values()),
        "validation": {
            "package": "available",
            "schema": "available" if "schema" in validators else "unavailable",
            "visual": "available" if "visual" in validators else "unavailable",
        },
    }


def _safe_provider_state(
    registry: ProviderRegistry, provider: Provider
) -> dict[str, Any]:
    try:
        return registry.detect(provider)
    except DocumentSkillsError as error:
        return unavailable_detector_state(
            str(provider.id),
            required=provider.required,
            reason=f"Provider detector failed: {error.code.value}",
            fallback_version=provider.version,
        )
