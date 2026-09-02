"""Typed provider catalog and fidelity-aware selection."""

from contextlib import ExitStack
from typing import Any

from document_skills_core.worker.invoke import (
    ProviderInvocationFailure,
    invoke_provider,
)

from ..contracts.errors import DocumentSkillsError, ErrorCode
from ..contracts.provider_values import normalize_provider_json
from .catalog import (
    Capability,
    DetectionEvidence,
    OperationBinding,
    ProviderDefinition,
    ProviderId,
    ProviderState,
)
from .provider_state import (
    detector_failure,
    normalize_detection_evidence,
    normalize_detector_state,
)

FIDELITY_RANK = {"core": 0, "enhanced": 1, "full": 2}
_RESULT_FIELD_TYPES: dict[str, type] = {
    "schema_version": str,
    "status": str,
    "operation": str,
    "provider_chain": list,
    "requested_fidelity": str,
    "achieved_fidelity": str,
    "degraded": bool,
    "degradations": list,
    "artifacts": list,
    "validation": dict,
    "warnings": list,
    "errors": list,
    "diagnostics": dict,
}
Provider = ProviderDefinition
OperationRegistration = OperationBinding


class ProviderRegistry:
    def __init__(self) -> None:
        self.providers: dict[str, Provider] = {}
        self.operations: dict[str, list[OperationRegistration]] = {}

    def register_provider(self, provider: Provider) -> None:
        provider_key = str(provider.id)
        if provider_key in self.providers:
            raise ValueError(f"Provider already registered: {provider_key}")
        self.providers[provider_key] = provider
        for capability in provider.capabilities:
            if provider.execute is None:
                continue
            self.operations.setdefault(capability.operation, []).append(
                OperationBinding(
                    capability.operation,
                    provider.id,
                    capability,
                    provider.execute,
                )
            )

    def select(self, operation: str, request: dict[str, Any]) -> OperationRegistration:
        candidates = self.operations.get(operation, [])
        if not candidates:
            raise DocumentSkillsError(
                ErrorCode.OPERATION_UNKNOWN,
                "The operation is not registered.",
                status="invalid_request",
                details={"operation": operation},
            )
        requested = request.get("options", {}).get("fidelity", "core")
        allow_degraded = request.get("options", {}).get("allow_degraded", False)
        available: list[tuple[tuple[int, int, int, int], OperationRegistration]] = []
        semantic_fallback: list[OperationRegistration] = []
        for registration in candidates:
            provider_id = str(registration.provider_id)
            provider = self.providers[provider_id]
            state = self.detect(provider)
            if state["available"] is not True or provider.execute is None:
                continue
            capability = registration.capability
            meets = FIDELITY_RANK[capability.fidelity] >= FIDELITY_RANK[requested]
            if not meets and not capability.semantic_equivalence:
                semantic_fallback.append(registration)
                continue
            score = (
                FIDELITY_RANK[capability.fidelity],
                capability.validation_strength,
                -provider.startup_cost,
                -provider.risk,
            )
            available.append((score, registration))
        if available:
            return max(available, key=lambda item: item[0])[1]
        if semantic_fallback and not allow_degraded:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Available fallback changes artifact semantics and requires explicit authorization.",
                status="enhancement_required",
                details={
                    "missing_capabilities": [operation],
                    "recommended_providers": sorted(
                        {str(item.provider_id) for item in semantic_fallback}
                    ),
                    "fallback": "Set options.allow_degraded only after reviewing semantic differences.",
                },
            )
        if semantic_fallback:
            return semantic_fallback[0]
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "No implemented provider is currently available for the operation.",
            status="unavailable",
            details={"operation": operation},
        )

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        with ExitStack() as leases:
            for provider in self.providers.values():
                if provider.operation_lease is not None:
                    leases.enter_context(provider.operation_lease())
            return self._execute_with_leases(request)

    def _execute_with_leases(self, request: dict[str, Any]) -> dict[str, Any]:
        registration = self.select(request["operation"], request)
        provider = self.providers[str(registration.provider_id)]
        if provider.execute is None:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Selected provider has no accepted implementation.",
            )
        try:
            result = invoke_provider(
                str(provider.id),
                "execute",
                provider.execute,
                request["operation"],
                request,
            )
        except ProviderInvocationFailure as error:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Provider execution failed safely.",
                details={
                    "provider": error.provider_id,
                    "phase": error.phase,
                    "reason_category": error.category,
                    "exception_class": error.exception_class,
                },
            ) from None
        try:
            normalized = _validate_provider_result(result)
        except Exception as error:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Provider returned an invalid result.",
                details={
                    "provider": provider.id,
                    "phase": "result",
                    "reason": type(error).__name__,
                },
            ) from error
        normalized["provider_chain"] = [str(provider.id), *normalized["provider_chain"]]
        return normalized

    @staticmethod
    def detect(provider: Provider) -> dict[str, Any]:
        try:
            raw_state = invoke_provider(str(provider.id), "detect", provider.detect)
        except ProviderInvocationFailure as error:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Provider detection failed safely.",
                details={
                    "provider": error.provider_id,
                    "phase": error.phase,
                    "reason_category": error.category,
                    "exception_class": error.exception_class,
                },
            ) from None
        try:
            return normalize_detector_state(
                raw_state,
                trusted_id=str(provider.id),
                required=provider.required,
            )
        except BaseException as error:
            raise detector_failure(
                str(provider.id), error, invalid_data=True
            ).as_error() from None


class ProviderCatalog(ProviderRegistry):
    """Production catalog: detector evidence cannot select identity or required state."""

    def register_provider(self, provider: Provider) -> None:
        if not isinstance(provider.id, ProviderId):
            raise TypeError("production provider id must be a ProviderId")
        super().register_provider(provider)

    def find_callable(self, provider_id: ProviderId | str) -> bool:
        """Return True when the provider is detected as available and has execute."""
        key = str(provider_id)
        provider = self.providers.get(key)
        if provider is None or provider.execute is None:
            return False
        try:
            state = self.detect(provider)
        except DocumentSkillsError:
            return False
        return state.get("available") is True

    @staticmethod
    def detect(provider: Provider) -> dict[str, Any]:
        try:
            raw_evidence = invoke_provider(str(provider.id), "detect", provider.detect)
        except ProviderInvocationFailure as error:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Provider detection failed safely.",
                details={
                    "provider": error.provider_id,
                    "phase": error.phase,
                    "reason_category": error.category,
                    "exception_class": error.exception_class,
                },
            ) from None
        try:
            evidence = normalize_detection_evidence(raw_evidence)
            return ProviderState(provider.id, provider.required, evidence).as_record()
        except BaseException as error:
            raise detector_failure(
                str(provider.id), error, invalid_data=True
            ).as_error() from None


def _validate_provider_result(result: Any) -> dict[str, Any]:
    if type(result) is not dict:
        raise TypeError("provider result must be a plain object")
    normalized = normalize_provider_json(result)
    if set(normalized) != set(_RESULT_FIELD_TYPES):
        raise ValueError("provider result fields do not match the canonical contract")
    for field_name, expected_type in _RESULT_FIELD_TYPES.items():
        if type(normalized[field_name]) is not expected_type:
            raise TypeError(f"provider result field has invalid type: {field_name}")
    if any(type(item) is not str for item in normalized["provider_chain"]):
        raise TypeError("provider_chain entries must be strings")
    return normalized
