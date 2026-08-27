"""Standard OOXML markers for source-neutral document node identities."""

from dataclasses import dataclass
from xml.etree.ElementTree import Element, SubElement

from .constants import qn

_TAG_PREFIX = "elftia.document-node/1:"
PARAGRAPH_NODE_TYPES = frozenset(
    {
        "abstract",
        "affiliations",
        "authors",
        "bibliography",
        "bibliography_entry",
        "citation",
        "equation",
        "equation_caption",
        "figure",
        "figure_caption",
        "heading",
        "keywords",
        "paragraph",
        "reference",
        "subtitle",
        "table_caption",
        "title",
    }
)
FIGURE_NODE_TYPES = frozenset({"figure"})
TABLE_NODE_TYPES = frozenset({"table"})
ALL_NODE_TYPES = PARAGRAPH_NODE_TYPES | TABLE_NODE_TYPES


@dataclass(frozen=True)
class SemanticNode:
    node_id: str
    node_type: str


def attach_semantic_node_marker(
    container: Element,
    *,
    node_id: str,
    node_type: str,
    marker_id: int,
) -> None:
    """Attach a locked, empty run-level content control to a body block."""

    paragraph = (
        container
        if container.tag == qn("w", "p")
        else next(container.iter(qn("w", "p")), None)
    )
    if paragraph is None:
        raise ValueError("A semantic document block must contain a paragraph.")
    marker = Element(qn("w", "sdt"))
    properties = SubElement(marker, qn("w", "sdtPr"))
    SubElement(properties, qn("w", "id"), {qn("w", "val"): str(marker_id)})
    SubElement(
        properties,
        qn("w", "tag"),
        {qn("w", "val"): f"{_TAG_PREFIX}{node_type}:{node_id}"},
    )
    SubElement(
        properties,
        qn("w", "alias"),
        {qn("w", "val"): f"Document node ({node_type})"},
    )
    SubElement(properties, qn("w", "lock"), {qn("w", "val"): "sdtLocked"})
    content = SubElement(marker, qn("w", "sdtContent"))
    SubElement(content, qn("w", "r"))
    insertion = 1 if paragraph.find(qn("w", "pPr")) is not None else 0
    paragraph.insert(insertion, marker)


def semantic_node_for(
    container: Element,
    *,
    allowed_types: frozenset[str] | None = None,
) -> SemanticNode | None:
    """Return the first recognized node marker within a projected block."""

    for marker in container.iter(qn("w", "sdt")):
        properties = marker.find(qn("w", "sdtPr"))
        tag = properties.find(qn("w", "tag")) if properties is not None else None
        value = tag.attrib.get(qn("w", "val"), "") if tag is not None else ""
        if not value.startswith(_TAG_PREFIX):
            continue
        remainder = value[len(_TAG_PREFIX) :]
        node_type, separator, node_id = remainder.partition(":")
        if not separator or not node_id:
            continue
        if allowed_types is not None and node_type not in allowed_types:
            continue
        return SemanticNode(node_id=node_id, node_type=node_type)
    return None
