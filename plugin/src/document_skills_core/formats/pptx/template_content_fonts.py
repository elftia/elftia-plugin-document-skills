"""Bounded effective-font resolution for template content lint."""

from __future__ import annotations

from typing import Any

from .constants import local_name
from .object_xml import drawable_elements, slide_shape_tree


def slide_font_context(package: Any, slide: dict[str, Any]) -> dict[str, Any]:
    """Parse bounded layout/master font defaults once for one slide."""

    context: dict[str, Any] = {
        "layout": [],
        "master": [],
        "styles": {},
    }
    roots = {}
    for owner_name in ("layout", "master"):
        owner = slide.get(owner_name)
        part = None if owner is None else owner.get("part")
        if part is None or part not in package.parts:
            continue
        root = package.xml(part)
        roots[owner_name] = root
        for candidate in drawable_elements(slide_shape_tree(root)):
            placeholder = _placeholder_key(candidate)
            if placeholder is None:
                continue
            defaults = {
                level: size
                for level in range(9)
                if (size := _placeholder_default_size(candidate, level)) is not None
            }
            if defaults:
                context[owner_name].append((placeholder, defaults))
    master_root = roots.get("master")
    if master_root is not None:
        _add_master_styles(context, master_root)
    return context


def resolved_font_sizes(
    element: Any,
    *,
    context: dict[str, Any],
    slot: dict[str, Any] | None,
) -> list[float]:
    """Resolve effective point sizes for the text-bearing runs in one object."""

    placeholder = _placeholder_key(element)
    resolved: set[float] = set()
    bodies = [
        node for node in element.iter() if local_name(node.tag) == "txBody"
    ] or [element]
    for body in bodies:
        for paragraph in (
            node for node in body if local_name(node.tag) == "p"
        ):
            if not any(
                node.text
                for node in paragraph.iter()
                if local_name(node.tag) == "t"
            ):
                continue
            level = _paragraph_level(paragraph)
            paragraph_default = _paragraph_default_size(paragraph)
            shape_default = _list_style_size(body, level)
            inherited = _inherited_font_size(context, placeholder, slot, level)
            found_run = False
            for run in paragraph:
                if local_name(run.tag) not in {"fld", "r"}:
                    continue
                if not any(
                    node.text for node in run.iter() if local_name(node.tag) == "t"
                ):
                    continue
                found_run = True
                size = _direct_property_size(run, "rPr")
                effective = size or paragraph_default or shape_default or inherited
                if effective is not None:
                    resolved.add(effective)
            if not found_run:
                effective = paragraph_default or shape_default or inherited
                if effective is not None:
                    resolved.add(effective)
    return sorted(resolved)


def _add_master_styles(context: dict[str, Any], master_root: Any) -> None:
    for style_name in ("bodyStyle", "otherStyle", "titleStyle"):
        style = next(
            (
                node
                for node in master_root.iter()
                if local_name(node.tag) == style_name
            ),
            None,
        )
        if style is None:
            continue
        for level in range(9):
            level_properties = next(
                (
                    node
                    for node in style
                    if local_name(node.tag) == f"lvl{level + 1}pPr"
                ),
                None,
            )
            size = _default_run_size(level_properties)
            if size is not None:
                context["styles"][(style_name, level)] = size


def _inherited_font_size(
    context: dict[str, Any],
    placeholder: tuple[str, str] | None,
    slot: dict[str, Any] | None,
    level: int,
) -> float | None:
    if placeholder is not None:
        for owner_name in ("layout", "master"):
            for actual, defaults in context[owner_name]:
                if _placeholder_matches(actual, placeholder) and level in defaults:
                    return defaults[level]
    style_name = _text_style_role(placeholder, slot)
    return context["styles"].get((style_name, level))


def _placeholder_key(element: Any) -> tuple[str, str] | None:
    placeholder = next(
        (node for node in element.iter() if local_name(node.tag) == "ph"),
        None,
    )
    if placeholder is None:
        return None
    return (
        placeholder.attrib.get("type", "body"),
        placeholder.attrib.get("idx", ""),
    )


def _placeholder_matches(actual: tuple[str, str], wanted: tuple[str, str]) -> bool:
    actual_type, actual_index = actual
    wanted_type, wanted_index = wanted
    if wanted_index:
        return actual_index == wanted_index
    return actual_type == wanted_type


def _text_style_role(
    placeholder: tuple[str, str] | None,
    slot: dict[str, Any] | None,
) -> str:
    role = "" if slot is None else str(slot.get("role", "")).lower()
    placeholder_role = "" if placeholder is None else placeholder[0]
    if placeholder_role in {"ctrTitle", "subTitle", "title"} or role in {
        "heading",
        "subtitle",
        "title",
    }:
        return "titleStyle"
    if placeholder is not None or role in {"body", "content"}:
        return "bodyStyle"
    return "otherStyle"


def _placeholder_default_size(element: Any, level: int) -> float | None:
    for paragraph in (
        node for node in element.iter() if local_name(node.tag) == "p"
    ):
        if _paragraph_level(paragraph) != level:
            continue
        size = _paragraph_default_size(paragraph)
        if size is not None:
            return size
    return _list_style_size(element, level)


def _paragraph_level(paragraph: Any) -> int:
    properties = next(
        (node for node in paragraph if local_name(node.tag) == "pPr"),
        None,
    )
    raw = "0" if properties is None else properties.attrib.get("lvl", "0")
    return int(raw) if raw.isdigit() and 0 <= int(raw) <= 8 else 0


def _paragraph_default_size(paragraph: Any) -> float | None:
    properties = next(
        (node for node in paragraph if local_name(node.tag) == "pPr"),
        None,
    )
    return _default_run_size(properties)


def _list_style_size(element: Any, level: int) -> float | None:
    style = next(
        (node for node in element.iter() if local_name(node.tag) == "lstStyle"),
        None,
    )
    if style is None:
        return None
    level_properties = next(
        (
            node
            for node in style
            if local_name(node.tag) == f"lvl{level + 1}pPr"
        ),
        None,
    )
    return _default_run_size(level_properties)


def _default_run_size(properties: Any) -> float | None:
    if properties is None:
        return None
    return _direct_property_size(properties, "defRPr")


def _direct_property_size(parent: Any, property_name: str) -> float | None:
    properties = next(
        (node for node in parent if local_name(node.tag) == property_name),
        None,
    )
    if properties is None:
        return None
    raw = properties.attrib.get("sz", "")
    return int(raw) / 100 if raw.isdigit() else None
