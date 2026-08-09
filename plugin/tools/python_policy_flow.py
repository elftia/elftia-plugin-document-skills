"""Bounded semantic summaries for local Python calls and literal containers."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TypeAlias

from .python_policy_values import BUILTINS_NAMESPACE_VALUES

UNKNOWN = "unknown"
UNKNOWN_POLICY_SENSITIVE = "unknown:policy-sensitive"
_MAX_CONTAINER_ITEMS = 64
_MAX_RESOLUTION_DEPTH = 8


@dataclass(frozen=True)
class ParameterValue:
    function_id: int
    name: str


@dataclass(frozen=True)
class LiteralContainer:
    kind: str
    items: tuple[AbstractValue, ...] = ()
    entries: tuple[tuple[object, AbstractValue], ...] = ()
    complete: bool = True
    policy_sensitive: bool = False


@dataclass(frozen=True)
class LiteralLookup:
    container: LiteralContainer


@dataclass(frozen=True)
class LocalFunction:
    function_id: int


AbstractValue: TypeAlias = (
    str | ParameterValue | LiteralContainer | LiteralLookup | LocalFunction
)


@dataclass(frozen=True)
class FunctionSummary:
    parameters: tuple[str, ...]
    defaults: tuple[tuple[str, AbstractValue], ...]
    returned: AbstractValue


def sequence_value(kind: str, values: list[AbstractValue]) -> LiteralContainer:
    retained = tuple(values[:_MAX_CONTAINER_ITEMS])
    complete = len(values) <= _MAX_CONTAINER_ITEMS
    return LiteralContainer(
        kind=kind,
        items=retained,
        complete=complete,
        policy_sensitive=any(is_policy_sensitive(item) for item in values),
    )


def mapping_value(
    keys: list[ast.expr | None],
    values: list[AbstractValue],
) -> LiteralContainer:
    entries: list[tuple[object, AbstractValue]] = []
    complete = len(keys) <= _MAX_CONTAINER_ITEMS
    for key_node, value in zip(keys, values):
        key = literal_key(key_node)
        if key is _MISSING:
            complete = False
        elif len(entries) < _MAX_CONTAINER_ITEMS:
            entries.append((key, value))
    return LiteralContainer(
        kind="dict",
        entries=tuple(entries),
        complete=complete,
        policy_sensitive=any(is_policy_sensitive(item) for item in values),
    )


def subscript_value(
    container: LiteralContainer,
    key_node: ast.expr,
) -> AbstractValue:
    key = literal_key(key_node)
    if container.kind in {"list", "tuple"} and type(key) is int:
        index = key if key >= 0 else len(container.items) + key
        if 0 <= index < len(container.items):
            return container.items[index]
    elif container.kind == "dict" and key is not _MISSING:
        for candidate, value in container.entries:
            if type(candidate) is type(key) and candidate == key:
                return value
        if container.complete:
            return "safe"
    return _uncertain(container)


def lookup_value(
    lookup: LiteralLookup,
    key_node: ast.expr | None,
    default: AbstractValue = "safe",
) -> AbstractValue:
    if key_node is None:
        return _uncertain(lookup.container)
    value = subscript_value(lookup.container, key_node)
    if value == "safe" and lookup.container.kind == "dict":
        return default
    return value


def unpack_values(
    value: AbstractValue,
    count: int,
) -> tuple[AbstractValue, ...] | None:
    if not isinstance(value, LiteralContainer):
        return None
    if value.complete and len(value.items) == count and value.kind in {
        "list",
        "tuple",
        "set",
    }:
        return value.items
    uncertain = _uncertain(value)
    return tuple(uncertain for _ in range(count))


def summarize_returns(values: list[AbstractValue]) -> AbstractValue:
    if not values:
        return "safe"
    first = values[0]
    if all(item == first for item in values[1:]):
        return first
    if any(is_policy_sensitive(item) for item in values):
        return UNKNOWN_POLICY_SENSITIVE
    return UNKNOWN


def resolve_summary(
    summary: FunctionSummary,
    function_id: int,
    positional: list[AbstractValue],
    keywords: dict[str, AbstractValue],
) -> AbstractValue:
    defaults = dict(summary.defaults)
    bindings = defaults | keywords
    for name, value in zip(summary.parameters, positional):
        bindings[name] = value
    return _resolve(summary.returned, function_id, bindings, 0)


def is_policy_sensitive(value: AbstractValue, depth: int = 0) -> bool:
    if isinstance(value, str):
        return value in {
            *BUILTINS_NAMESPACE_VALUES,
            "dangerous",
            UNKNOWN_POLICY_SENSITIVE,
        }
    if isinstance(value, LiteralContainer):
        return value.policy_sensitive
    if isinstance(value, LiteralLookup):
        return value.container.policy_sensitive
    return False


def literal_key(node: ast.expr | None) -> object:
    if node is None:
        return _MISSING
    if isinstance(node, ast.Constant) and type(node.value) in {str, int}:
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        if isinstance(node.operand, ast.Constant) and type(node.operand.value) is int:
            return -node.operand.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = literal_key(node.left)
        right = literal_key(node.right)
        if type(left) is str and type(right) is str:
            return left + right
    return _MISSING


def _resolve(
    value: AbstractValue,
    function_id: int,
    bindings: dict[str, AbstractValue],
    depth: int,
) -> AbstractValue:
    if depth >= _MAX_RESOLUTION_DEPTH:
        return UNKNOWN_POLICY_SENSITIVE if is_policy_sensitive(value) else UNKNOWN
    if isinstance(value, ParameterValue):
        if value.function_id != function_id:
            return value
        return bindings.get(value.name, UNKNOWN)
    if isinstance(value, LiteralContainer):
        items = tuple(
            _resolve(item, function_id, bindings, depth + 1)
            for item in value.items
        )
        entries = tuple(
            (key, _resolve(item, function_id, bindings, depth + 1))
            for key, item in value.entries
        )
        return LiteralContainer(
            kind=value.kind,
            items=items,
            entries=entries,
            complete=value.complete,
            policy_sensitive=any(is_policy_sensitive(item) for item in items)
            or any(is_policy_sensitive(item) for _, item in entries),
        )
    return value


def _uncertain(container: LiteralContainer) -> str:
    return UNKNOWN_POLICY_SENSITIVE if container.policy_sensitive else UNKNOWN


_MISSING = object()
