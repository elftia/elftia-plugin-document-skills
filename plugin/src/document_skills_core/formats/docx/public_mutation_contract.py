"""Edit, merge, replacement, and template operation contracts."""

from typing import Any

from .constants import MAX_RULES, MAX_VARIABLES
from .contract_utils import (
    _IDENTIFIER,
    _boolean,
    _exact_keys,
    _integer,
    _invalid,
    _text,
)

def _parse_edit(value: dict[str, Any]) -> dict[str, Any]:
    from .edit_contract import parse_edit

    return parse_edit(value)


def _parse_merge(value: dict[str, Any]) -> dict[str, Any]:
    from .merge_contract import parse_merge

    return parse_merge(value)

def _parse_replace(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"case_sensitive", "replacements"})
    rules = value.get("replacements")
    if type(rules) is not list or not rules or len(rules) > MAX_RULES:
        _invalid("replacements must be a non-empty bounded array.", field="replacements")
    parsed = []
    for index, rule in enumerate(rules):
        if type(rule) is not dict:
            _invalid("Each replacement must be an object.", field=f"replacements.{index}")
        _exact_keys(rule, {"expected_matches", "replace", "search"})
        search = _text(rule.get("search"), f"replacements.{index}.search", allow_empty=False)
        replace = _text(rule.get("replace"), f"replacements.{index}.replace")
        expected = rule.get("expected_matches")
        if expected is not None:
            expected = _integer(expected, 0, 1_000_000)
        parsed.append(
            {"search": search, "replace": replace, "expected_matches": expected}
        )
    return {
        "case_sensitive": _boolean(value.get("case_sensitive", True), "case_sensitive"),
        "replacements": parsed,
    }


def _parse_template(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"missing_policy", "regions", "style_overlay", "variables"})
    variables = value.get("variables")
    if type(variables) is not dict or len(variables) > MAX_VARIABLES:
        _invalid("variables must be a bounded object.", field="variables")
    flattened: dict[str, str] = {}
    _flatten_variables(variables, "", flattened, depth=0)
    if len(
        str(sorted(flattened.items())).encode("utf-8", errors="strict")
    ) > 512 * 1024:
        _invalid("Template variables exceed the aggregate byte limit.")
    missing_policy = value.get("missing_policy", "error")
    if missing_policy != "error":
        _invalid("Only the fail-closed missing_policy 'error' is supported.")
    parsed = {"variables": flattened, "missing_policy": missing_policy}
    if "style_overlay" in value:
        from .style_contract import parse_style_overlay

        parsed["style_overlay"] = parse_style_overlay(value["style_overlay"])
    if "regions" in value:
        from .template_region_contract import parse_template_regions

        parsed["regions"] = parse_template_regions(value["regions"])
    return parsed


def _flatten_variables(
    value: dict[str, Any],
    prefix: str,
    target: dict[str, str],
    *,
    depth: int,
) -> None:
    if depth > 8:
        _invalid("Template variables exceed the nesting limit.")
    for raw_name, item in value.items():
        if type(raw_name) is not str:
            _invalid("Template variable names must be strings.")
        name = f"{prefix}.{raw_name}" if prefix else raw_name
        if not _IDENTIFIER.fullmatch(name):
            _invalid("Template variable names must be bounded ASCII identifiers.", field=name)
        if type(item) is dict:
            _flatten_variables(item, name, target, depth=depth + 1)
        elif item is None or type(item) in {str, int, float, bool}:
            rendered = (
                ""
                if item is None
                else str(item).lower() if type(item) is bool else str(item)
            )
            target[name] = _text(rendered, name)
        else:
            _invalid("Template values must be scalar.", field=name)
        if len(target) > MAX_VARIABLES:
            _invalid("Template variables exceed the item limit.")
