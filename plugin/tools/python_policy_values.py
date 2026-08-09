"""Abstract values for builtin-namespace mapping lookups."""

import ast

from .python_policy_definitions import (
    DANGEROUS_ATTRIBUTES,
    DANGEROUS_BUILTINS,
    MCP_REGISTRATION,
    is_reflective_dunder,
    literal_string,
    normalized,
)

BUILTINS_NAMESPACE_VALUES = {"module:builtins", "namespace:builtins"}
BOUND_BUILTINS_LOOKUP = "callable:bound-builtins-lookup"
DICT_LOOKUP = "callable:dict-lookup"
DICT_TYPE = "type:dict"
_LOOKUP_ATTRIBUTES = {"__getitem__", "get"}
_STRING_VALUE_PREFIX = "string:"


def string_value(node: ast.expr) -> str | None:
    value = literal_string(node)
    return None if value is None else f"{_STRING_VALUE_PREFIX}{value}"


def attribute_value(base: str, attribute: str) -> str | None:
    if attribute not in _LOOKUP_ATTRIBUTES:
        return None
    if base in BUILTINS_NAMESPACE_VALUES:
        return BOUND_BUILTINS_LOOKUP
    if base == DICT_TYPE:
        return DICT_LOOKUP
    return None


def rejects_builtin_lookup(
    target: str,
    argument_nodes: list[ast.expr],
    argument_values: list[str],
) -> bool:
    if target == BOUND_BUILTINS_LOOKUP:
        key_index = 0
    elif (
        target == DICT_LOOKUP
        and argument_values
        and argument_values[0] in BUILTINS_NAMESPACE_VALUES
    ):
        key_index = 1
    else:
        return False
    if len(argument_nodes) <= key_index:
        return False
    key = literal_string(argument_nodes[key_index]) or _decoded_string(
        argument_values[key_index]
    )
    return key is None or _dangerous_namespace_key(key)


def is_policy_sensitive_default(value: str) -> bool:
    return value in {
        *BUILTINS_NAMESPACE_VALUES,
        BOUND_BUILTINS_LOOKUP,
        DICT_LOOKUP,
    }


def _decoded_string(value: object) -> str | None:
    if isinstance(value, str) and value.startswith(_STRING_VALUE_PREFIX):
        return value.removeprefix(_STRING_VALUE_PREFIX)
    return None


def _dangerous_namespace_key(key: str) -> bool:
    return (
        key in DANGEROUS_BUILTINS
        or key in DANGEROUS_ATTRIBUTES
        or is_reflective_dunder(key)
        or normalized(key) in MCP_REGISTRATION
    )
