"""Domain constraints composed over the source-neutral document spec."""

from typing import Any

from .contracts import _exact_keys, _invalid

_SUPPORTED = {
    "academic-paper": frozenset({"en-US", "zh-CN"}),
    "technical-report": frozenset({"en-US", "zh-CN"}),
}
_ACADEMIC_SINGLETONS = ("title", "authors", "abstract", "keywords")
_CAPTION_TARGETS = {
    "figure_caption": "figure",
    "table_caption": "table",
    "equation_caption": "equation",
}
_BIBLIOGRAPHY_TYPES = frozenset({"bibliography", "bibliography_entry", "citation"})


def parse_domain_profile(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if type(value) is not dict:
        _invalid("domain_profile must be an object.", field="domain_profile")
    _exact_keys(value, {"citation_style", "id", "locale", "version"})
    profile_id = value.get("id")
    version = value.get("version")
    locale = value.get("locale")
    if (
        profile_id not in _SUPPORTED
        or version != "1.0"
        or locale not in _SUPPORTED.get(profile_id, frozenset())
    ):
        _invalid(
            "Unsupported DOCX domain profile, version, or locale.",
            field="domain_profile",
        )
    result = {"id": profile_id, "version": version, "locale": locale}
    citation_style = value.get("citation_style")
    if citation_style is not None:
        if citation_style not in {"author-year", "numeric"}:
            _invalid("Unsupported citation style.", field="domain_profile.citation_style")
        result["citation_style"] = citation_style
    return result


def normalize_domain_nodes(
    nodes: list[dict[str, Any]],
    profile: dict[str, str] | None,
) -> None:
    """Validate a domain recipe and normalize its labels in place."""

    if profile is None:
        if any(
            node.get("node_type") in set(_CAPTION_TARGETS) | _BIBLIOGRAPHY_TYPES
            for node in nodes
        ):
            _invalid("Caption and bibliography nodes require a domain_profile.")
        return
    _validate_caption_targets(nodes)
    _validate_and_format_bibliography(nodes, profile)
    if profile["id"] == "academic-paper":
        _validate_academic_structure(nodes)
        _format_academic_roles(nodes, locale=profile["locale"])


def _validate_academic_structure(nodes: list[dict[str, Any]]) -> None:
    positions: dict[str, list[int]] = {}
    for index, node in enumerate(nodes):
        positions.setdefault(node["node_type"], []).append(index)
    for role in _ACADEMIC_SINGLETONS:
        if len(positions.get(role, [])) != 1:
            _invalid(
                "Academic papers require exactly one structural role.",
                role=role,
            )
    ordered_roles = ["title", "authors", "abstract", "keywords"]
    order = [positions[role][0] for role in ordered_roles]
    if order != sorted(order):
        _invalid(
            "Academic paper front-matter roles are out of order.",
            expected=ordered_roles,
        )
    headings = positions.get("heading", [])
    if not headings or headings[0] <= order[-1]:
        _invalid("Academic paper body must start with a heading after front matter.")


def _validate_caption_targets(nodes: list[dict[str, Any]]) -> None:
    by_id = {node["node_id"]: (index, node) for index, node in enumerate(nodes)}
    targets_seen: set[str] = set()
    for index, node in enumerate(nodes):
        expected_type = _CAPTION_TARGETS.get(node.get("node_type"))
        if expected_type is None:
            continue
        target_id = node["target_id"]
        target_entry = by_id.get(target_id)
        if target_entry is None or target_entry[1]["node_type"] != expected_type:
            _invalid(
                "Caption target is missing or has the wrong semantic type.",
                caption=node["node_id"],
                target=target_id,
                expected_type=expected_type,
            )
        if target_id in targets_seen:
            _invalid("A semantic object cannot have duplicate captions.", target=target_id)
        if abs(index - target_entry[0]) != 1:
            _invalid(
                "Caption must be adjacent to its semantic object.",
                caption=node["node_id"],
                target=target_id,
            )
        targets_seen.add(target_id)


def _format_academic_roles(nodes: list[dict[str, Any]], *, locale: str) -> None:
    counters = {"figure_caption": 0, "table_caption": 0, "equation_caption": 0}
    labels = (
        {
            "figure_caption": "图",
            "table_caption": "表",
            "equation_caption": "公式",
        }
        if locale == "zh-CN"
        else {
            "figure_caption": "Figure",
            "table_caption": "Table",
            "equation_caption": "Equation",
        }
    )
    for node in nodes:
        node_type = node["node_type"]
        if node_type == "authors":
            node["text"] = ", ".join(node["items"])
        elif node_type == "affiliations":
            node["text"] = "; ".join(node["items"])
        elif node_type == "keywords":
            prefix = "关键词：" if locale == "zh-CN" else "Keywords: "
            delimiter = "；" if locale == "zh-CN" else "; "
            node["text"] = prefix + delimiter.join(node["items"])
        elif node_type in counters:
            counters[node_type] += 1
            number = counters[node_type]
            if locale == "zh-CN":
                node["text"] = f"{labels[node_type]} {number}\u3000{node['text']}"
            elif node_type == "equation_caption":
                node["text"] = f"{labels[node_type]} ({number}). {node['text']}"
            else:
                node["text"] = f"{labels[node_type]} {number}. {node['text']}"


def _validate_and_format_bibliography(
    nodes: list[dict[str, Any]],
    profile: dict[str, str],
) -> None:
    citations = [node for node in nodes if node["node_type"] == "citation"]
    entries = [node for node in nodes if node["node_type"] == "bibliography_entry"]
    bibliographies = [node for node in nodes if node["node_type"] == "bibliography"]
    if not citations and not entries and not bibliographies:
        return
    if len(bibliographies) != 1:
        _invalid("Citations require exactly one bibliography node.")
    entry_by_key: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if entry["key"] in entry_by_key:
            _invalid("Bibliography keys must be unique.", key=entry["key"])
        entry_by_key[entry["key"]] = entry
    cited = {key for citation in citations for key in citation["keys"]}
    available = set(entry_by_key)
    if cited != available:
        _invalid(
            "Citation and bibliography keys must match bidirectionally.",
            missing_entries=sorted(cited - available),
            uncited_entries=sorted(available - cited),
        )
    bibliography_index = nodes.index(bibliographies[0])
    if any(nodes.index(entry) <= bibliography_index for entry in entries):
        _invalid("Bibliography entries must follow the bibliography heading.")
    style = profile.get("citation_style", "author-year")
    numbers = {entry["key"]: index for index, entry in enumerate(entries, start=1)}
    for citation in citations:
        if style == "numeric":
            citation["text"] = "[" + ", ".join(
                str(numbers[key]) for key in citation["keys"]
            ) + "]"
        else:
            citation["text"] = "(" + "; ".join(
                f"{_family_name(entry_by_key[key]['authors'][0])}, "
                f"{entry_by_key[key]['year']}"
                for key in citation["keys"]
            ) + ")"
    bibliographies[0]["text"] = (
        "参考文献" if profile["locale"] == "zh-CN" else "References"
    )
    for entry in entries:
        author_text = "; ".join(entry["authors"])
        container = f" {entry['container']}." if entry["container"] else ""
        if style == "numeric":
            entry["text"] = (
                f"[{numbers[entry['key']]}] {author_text}. {entry['year']}. "
                f"{entry['title']}.{container}"
            )
        else:
            formatted_authors = "; ".join(
                _bibliography_name(author) for author in entry["authors"]
            )
            entry["text"] = (
                f"{formatted_authors}. ({entry['year']}). {entry['title']}.{container}"
            )


def _family_name(author: str) -> str:
    return author.rsplit(" ", 1)[-1]


def _bibliography_name(author: str) -> str:
    given, separator, family = author.rpartition(" ")
    return f"{family}, {given}" if separator else author
