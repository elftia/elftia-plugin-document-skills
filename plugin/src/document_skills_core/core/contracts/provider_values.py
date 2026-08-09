"""Bounded normalization for untrusted provider-owned JSON values."""

from dataclasses import dataclass
import math
from typing import Any

MAX_PROVIDER_DEPTH = 32
MAX_PROVIDER_ITEMS = 100_000
MAX_PROVIDER_STRING_BYTES = 1_048_576
MAX_PROVIDER_TOTAL_STRING_BYTES = 4_194_304
MAX_PROVIDER_INTEGER_DIGITS = 1_024
_MAX_INTEGER_BITS = 3_402


@dataclass
class _Budget:
    items: int = 0
    string_bytes: int = 0


def normalize_provider_json(value: Any) -> Any:
    """Return plain bounded JSON containers or reject the provider value."""
    return _normalize(value, depth=0, budget=_Budget())


def _normalize(value: Any, *, depth: int, budget: _Budget) -> Any:
    if depth > MAX_PROVIDER_DEPTH:
        raise ValueError("provider result exceeds nesting limit")
    budget.items += 1
    if budget.items > MAX_PROVIDER_ITEMS:
        raise ValueError("provider result exceeds item limit")

    if value is None or type(value) is bool:
        return value
    if type(value) is str:
        _consume_string(value, budget)
        return value
    if type(value) is int:
        _validate_integer(value)
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("provider result contains a non-finite number")
        return value
    if type(value) is list:
        return [
            _normalize(child, depth=depth + 1, budget=budget) for child in value
        ]
    if type(value) is dict:
        normalized: dict[str, Any] = {}
        for key, child in value.items():
            if type(key) is not str:
                raise TypeError("provider result object keys must be strings")
            _consume_string(key, budget)
            normalized[key] = _normalize(
                child, depth=depth + 1, budget=budget
            )
        return normalized
    raise TypeError("provider result contains a non-JSON value")


def _consume_string(value: str, budget: _Budget) -> None:
    encoded = value.encode("utf-8", errors="strict")
    size = len(encoded)
    if size > MAX_PROVIDER_STRING_BYTES:
        raise ValueError("provider result string exceeds byte limit")
    budget.string_bytes += size
    if budget.string_bytes > MAX_PROVIDER_TOTAL_STRING_BYTES:
        raise ValueError("provider result strings exceed aggregate byte limit")


def _validate_integer(value: int) -> None:
    absolute = abs(value)
    if absolute.bit_length() > _MAX_INTEGER_BITS:
        raise ValueError("provider result integer exceeds digit limit")
    digits = 1 if absolute == 0 else len(str(absolute))
    if digits > MAX_PROVIDER_INTEGER_DIGITS:
        raise ValueError("provider result integer exceeds digit limit")
