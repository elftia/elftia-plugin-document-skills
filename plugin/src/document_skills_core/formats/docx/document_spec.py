"""Versioned, source-neutral document specification for DOCX creation."""

import re
from typing import Any

from .constants import MAX_HEADING_LEVEL
from .contracts import _exact_keys, _integer, _invalid, _text
from .create_contract import (
    MAX_CREATE_IMAGES,
    _enforce_aggregate_budgets,
    _image_payload,
    _parse_metadata,
    _parse_sections,
    _parse_table,
    _story_text,
)
from .domain_profiles import normalize_domain_nodes, parse_domain_profile
from .references import plan_document_references
from .style_profiles import parse_style_profile, style_id_for

_NODE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")


def parse_document_spec(value: Any) -> dict[str, Any]:
    """Validate v1 semantic nodes and normalize them into the create IR."""

    if type(value) is not dict:
        _invalid("document_spec must be an object.", field="document_spec")
    _exact_keys(
        value,
        {
            "footer",
            "header",
            "domain_profile",
            "metadata",
            "nodes",
            "resources",
            "sections",
            "style_profile",
            "version",
        },
    )
    if value.get("version") != "1.0":
        _invalid(
            "Only document_spec version 1.0 is supported.",
            field="document_spec.version",
        )
    _enforce_aggregate_budgets(value)
    resources = _parse_resources(value.get("resources", {}))
    style_profile = parse_style_profile(value.get("style_profile"))
    domain_profile = parse_domain_profile(value.get("domain_profile"))
    nodes = value.get("nodes")
    if type(nodes) is not list or not 1 <= len(nodes) <= 512:
        _invalid("document_spec.nodes must be a non-empty bounded array.")

    parsed_nodes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    image_count = 0
    for index, node in enumerate(nodes):
        parsed = _parse_node(node, index, resources, style_profile)
        node_id = parsed["node_id"]
        if node_id in seen_ids:
            _invalid(
                "Document node IDs must be unique.",
                field=f"document_spec.nodes.{index}.id",
            )
        seen_ids.add(node_id)
        image_count += parsed["type"] == "image"
        parsed_nodes.append(parsed)
    normalize_domain_nodes(parsed_nodes, domain_profile)
    plan_document_references(parsed_nodes)
    if image_count > MAX_CREATE_IMAGES:
        _invalid(
            "Document spec exceeds the image count limit.",
            budget="document_spec.total_images",
            ceiling=MAX_CREATE_IMAGES,
        )

    report = {
        "blocks": parsed_nodes,
        "image": None,
        "header": _story_text(value.get("header"), "document_spec.header"),
        "footer": _story_text(value.get("footer"), "document_spec.footer"),
        "sections": _parse_sections(value.get("sections")),
        "metadata": _parse_metadata(value.get("metadata", {})),
        "document_spec_version": "1.0",
        "domain_profile": domain_profile,
        "style_profile": style_profile,
    }
    _enforce_aggregate_budgets(report)
    return report


def _parse_resources(value: Any) -> dict[str, dict[str, Any]]:
    if type(value) is not dict or len(value) > MAX_CREATE_IMAGES:
        _invalid("document_spec.resources must be a bounded object.")
    resources: dict[str, dict[str, Any]] = {}
    for resource_id, resource in value.items():
        _stable_id(resource_id, f"document_spec.resources.{resource_id}")
        if type(resource) is not dict:
            _invalid("Each document resource must be an object.")
        _exact_keys(resource, {"path", "type"})
        if resource.get("type") != "image":
            _invalid(
                "Unsupported document resource type.",
                field=f"document_spec.resources.{resource_id}.type",
            )
        resources[resource_id] = {
            "type": "image",
            "path": _text(
                resource.get("path"),
                f"document_spec.resources.{resource_id}.path",
                allow_empty=False,
            ),
        }
    return resources


def _parse_node(
    value: Any,
    index: int,
    resources: dict[str, dict[str, Any]],
    style_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    field = f"document_spec.nodes.{index}"
    if type(value) is not dict:
        _invalid("Each document node must be an object.", field=field)
    kind = value.get("type")
    node_id = _stable_id(value.get("id"), f"{field}.id")
    if kind == "title":
        _exact_keys(value, {"id", "text", "type"})
        return {
            "type": "paragraph",
            "text": _text(value.get("text"), f"{field}.text", False),
            "style": style_id_for(style_profile, "title"),
            "node_id": node_id,
            "node_type": kind,
        }
    if kind == "heading":
        _exact_keys(value, {"id", "level", "text", "type"})
        parsed = {
            "type": "heading",
            "text": _text(value.get("text"), f"{field}.text", False),
            "level": _integer(value.get("level", 1), 1, MAX_HEADING_LEVEL),
            "node_id": node_id,
            "node_type": kind,
        }
        parsed["style"] = style_id_for(
            style_profile,
            "heading",
            heading_level=parsed["level"],
        )
        return parsed
    if kind == "paragraph":
        _exact_keys(value, {"id", "text", "type"})
        return {
            "type": "paragraph",
            "text": _text(value.get("text"), f"{field}.text"),
            "style": style_id_for(style_profile, "paragraph"),
            "node_id": node_id,
            "node_type": kind,
        }
    if kind in {"subtitle", "abstract"}:
        _exact_keys(value, {"id", "text", "type"})
        return {
            "type": "paragraph",
            "text": _text(value.get("text"), f"{field}.text", False),
            "style": style_id_for(style_profile, kind),
            "node_id": node_id,
            "node_type": kind,
        }
    if kind in {"authors", "affiliations", "keywords"}:
        _exact_keys(value, {"id", "items", "type"})
        items = _items(value.get("items"), f"{field}.items")
        return {
            "type": "paragraph",
            "text": "; ".join(items),
            "items": items,
            "style": style_id_for(style_profile, kind),
            "node_id": node_id,
            "node_type": kind,
        }
    if kind in {"figure_caption", "table_caption", "equation_caption"}:
        _exact_keys(value, {"id", "target", "text", "type"})
        return {
            "type": "paragraph",
            "text": _text(value.get("text"), f"{field}.text", False),
            "target_id": _stable_id(value.get("target"), f"{field}.target"),
            "style": style_id_for(style_profile, "caption"),
            "node_id": node_id,
            "node_type": kind,
        }
    if kind == "reference":
        _exact_keys(value, {"id", "target", "text", "type"})
        return {
            "type": "reference",
            "text": _text(value.get("text"), f"{field}.text", False),
            "target_id": _stable_id(value.get("target"), f"{field}.target"),
            "style": style_id_for(style_profile, "paragraph"),
            "node_id": node_id,
            "node_type": kind,
        }
    if kind == "equation":
        _exact_keys(value, {"id", "linear", "type"})
        linear = _text(value.get("linear"), f"{field}.linear", False)
        if any(marker in linear for marker in ("\\", "{", "}", "$")):
            _invalid(
                "Equation linear text does not accept LaTeX commands.",
                field=f"{field}.linear",
            )
        return {
            "type": "equation",
            "linear": linear,
            "style": style_id_for(style_profile, "equation"),
            "node_id": node_id,
            "node_type": kind,
        }
    if kind == "citation":
        _exact_keys(value, {"id", "keys", "type"})
        return {
            "type": "paragraph",
            "text": "",
            "keys": _identifiers(value.get("keys"), f"{field}.keys"),
            "style": style_id_for(style_profile, "citation"),
            "node_id": node_id,
            "node_type": kind,
        }
    if kind == "bibliography":
        _exact_keys(value, {"id", "type"})
        return {
            "type": "paragraph",
            "text": "",
            "style": style_id_for(style_profile, "bibliography_heading"),
            "node_id": node_id,
            "node_type": kind,
        }
    if kind == "bibliography_entry":
        _exact_keys(
            value,
            {"authors", "container", "id", "key", "title", "type", "year"},
        )
        return {
            "type": "paragraph",
            "text": "",
            "key": _stable_id(value.get("key"), f"{field}.key"),
            "authors": _items(value.get("authors"), f"{field}.authors"),
            "year": _integer(value.get("year"), 0, 9999),
            "title": _text(value.get("title"), f"{field}.title", False),
            "container": _text(value.get("container", ""), f"{field}.container"),
            "style": style_id_for(style_profile, "bibliography"),
            "node_id": node_id,
            "node_type": kind,
        }
    if kind == "table":
        _exact_keys(
            value,
            {
                "borders",
                "column_widths_twips",
                "id",
                "rows",
                "type",
                "width_twips",
            },
        )
        table = _parse_table(
            {
                key: item
                for key, item in value.items()
                if key not in {"id"}
            }
        )
        return {
            **table,
            "style": style_id_for(style_profile, "table"),
            "direct_header_bold": style_profile is None,
            "node_id": node_id,
            "node_type": kind,
        }
    if kind == "figure":
        _exact_keys(
            value,
            {"alt_text", "id", "resource", "type", "width_inches"},
        )
        resource_id = _stable_id(value.get("resource"), f"{field}.resource")
        resource = resources.get(resource_id)
        if resource is None:
            _invalid(
                "Figure references an unknown document resource.",
                field=f"{field}.resource",
            )
        image = _image_payload(
            {
                "path": resource["path"],
                "alt_text": value.get("alt_text", "Document figure"),
                "width_inches": value.get("width_inches", 4),
            },
            field,
        )
        return {
            "type": "image",
            **image,
            "node_id": node_id,
            "node_type": kind,
            "resource_id": resource_id,
            "style": style_id_for(style_profile, "figure"),
        }
    _invalid("Unsupported document node type.", field=f"{field}.type")


def _stable_id(value: Any, field: str) -> str:
    identifier = _text(value, field, allow_empty=False)
    if not _NODE_ID.fullmatch(identifier):
        _invalid(
            "Stable IDs must be bounded ASCII identifiers.",
            field=field,
        )
    return identifier


def _items(value: Any, field: str) -> list[str]:
    if type(value) is not list or not 1 <= len(value) <= 64:
        _invalid("Semantic item list must be a non-empty bounded array.", field=field)
    return [
        _text(item, f"{field}.{index}", allow_empty=False)
        for index, item in enumerate(value)
    ]


def _identifiers(value: Any, field: str) -> list[str]:
    if type(value) is not list or not 1 <= len(value) <= 64:
        _invalid("Identifier list must be a non-empty bounded array.", field=field)
    result = [_stable_id(item, f"{field}.{index}") for index, item in enumerate(value)]
    if len(set(result)) != len(result):
        _invalid("Identifier list values must be unique.", field=field)
    return result
