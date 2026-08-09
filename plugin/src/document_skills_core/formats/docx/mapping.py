"""Barrier-aware WordprocessingML text/run mapping."""

from dataclasses import dataclass, field
import hashlib
from typing import Iterable
from xml.etree.ElementTree import Element

from .constants import local_name, qn
from .package import OpcPackage
from .relationships import relationship_map

_PROTECTED_CONTAINERS = {
    "comment",
    "customXml",
    "del",
    "fldSimple",
    "ins",
    "moveFrom",
    "moveTo",
    "sdt",
}
_BARRIER_NODES = {
    "bookmarkEnd",
    "bookmarkStart",
    "br",
    "commentRangeEnd",
    "commentRangeStart",
    "drawing",
    "fldChar",
    "instrText",
    "object",
    "tab",
}


@dataclass
class TextRef:
    node: Element
    run: Element
    run_index: int
    hyperlink_id: str | None
    start: int
    end: int
    original: str


@dataclass
class TextGroup:
    refs: list[TextRef] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(item.original for item in self.refs)


@dataclass
class ParagraphMap:
    paragraph: Element
    groups: list[TextGroup]
    protected_text: str
    full_text: str
    run_summaries: list[dict[str, object]]
    hyperlink_ids: list[str]


@dataclass(frozen=True)
class Story:
    kind: str
    part: str
    root: Element


def map_paragraph(paragraph: Element) -> ParagraphMap:
    groups: list[TextGroup] = []
    active = TextGroup()
    protected: list[str] = []
    run_summaries: list[dict[str, object]] = []
    hyperlink_ids: list[str] = []
    run_index = 0

    def flush() -> None:
        nonlocal active
        if active.refs:
            groups.append(active)
        active = TextGroup()

    def walk(node: Element, *, hyperlink_id: str | None = None, blocked: bool = False) -> None:
        nonlocal run_index
        name = local_name(node.tag)
        now_blocked = blocked or name in _PROTECTED_CONTAINERS
        if name in _BARRIER_NODES:
            flush()
            protected.extend(_text_descendants(node))
            return
        if now_blocked and not blocked:
            flush()
            protected.extend(_text_descendants(node))
            return
        if name == "hyperlink":
            flush()
            hyperlink_id = node.attrib.get(qn("r", "id"))
            if hyperlink_id:
                hyperlink_ids.append(hyperlink_id)
            for child in node:
                walk(child, hyperlink_id=hyperlink_id, blocked=now_blocked)
            flush()
            return
        if name == "r":
            current_run = run_index
            run_index += 1
            texts = [
                child.text or ""
                for child in node
                if local_name(child.tag) == "t"
            ]
            run_summaries.append(
                {
                    "index": current_run,
                    "text": "".join(texts),
                    "bold": node.find(f"./{qn('w', 'rPr')}/{qn('w', 'b')}") is not None,
                    "italic": node.find(f"./{qn('w', 'rPr')}/{qn('w', 'i')}") is not None,
                    "style": _value(
                        node.find(f"./{qn('w', 'rPr')}/{qn('w', 'rStyle')}")
                    ),
                    "hyperlink_id": hyperlink_id,
                }
            )
            for child in node:
                child_name = local_name(child.tag)
                if child_name == "t":
                    text = child.text or ""
                    start = sum(len(item.original) for item in active.refs)
                    active.refs.append(
                        TextRef(
                            child,
                            node,
                            current_run,
                            hyperlink_id,
                            start,
                            start + len(text),
                            text,
                        )
                    )
                elif child_name in _BARRIER_NODES or child_name in {
                    "delText",
                    "instrText",
                }:
                    flush()
                    protected.extend(_text_descendants(child) or [child.text or ""])
            return
        for child in node:
            walk(child, hyperlink_id=hyperlink_id, blocked=now_blocked)

    walk(paragraph)
    flush()
    full_text = "".join(_text_descendants(paragraph))
    return ParagraphMap(
        paragraph,
        groups,
        "".join(protected),
        full_text,
        run_summaries,
        sorted(set(hyperlink_ids)),
    )


def document_stories(package: OpcPackage, *, include_headers_footers: bool = True) -> list[Story]:
    stories = [Story("body", "word/document.xml", package.xml("word/document.xml"))]
    if not include_headers_footers:
        return stories
    relationships = relationship_map(package.relationships, "word/document.xml")
    targets = []
    for relationship in relationships.values():
        terminal = relationship.relationship_type.rsplit("/", 1)[-1]
        if terminal in {"header", "footer"} and relationship.resolved_target:
            targets.append((terminal, relationship.resolved_target))
    for kind, part in sorted(set(targets), key=lambda item: (item[0], item[1])):
        stories.append(Story(kind, part, package.xml(part)))
    return stories


def protected_comment_text(package: OpcPackage) -> str:
    comments = []
    for name in sorted(package.parts):
        terminal = name.rsplit("/", 1)[-1].casefold()
        if name.startswith("word/") and terminal.startswith("comments") and name.endswith(".xml"):
            root = package.xml(name)
            comments.extend(_text_descendants(root))
    return "".join(comments)


def iter_paragraphs(root: Element) -> Iterable[Element]:
    yield from root.iter(qn("w", "p"))


def paragraph_style(paragraph: Element) -> str | None:
    return _value(paragraph.find(f"./{qn('w', 'pPr')}/{qn('w', 'pStyle')}"))


def paragraph_numbering(paragraph: Element) -> dict[str, str] | None:
    properties = paragraph.find(f"./{qn('w', 'pPr')}/{qn('w', 'numPr')}")
    if properties is None:
        return None
    number_id = _value(properties.find(qn("w", "numId")))
    level = _value(properties.find(qn("w", "ilvl")))
    return {"numbering_id": number_id or "", "level": level or "0"}


def semantic_tree_digest(
    root: Element,
    *,
    ignore_text_space_for: set[int] | None = None,
) -> str:
    """Hash semantic XML structure while ignoring target-node space hints."""
    ignored = ignore_text_space_for or set()
    space = "{http://www.w3.org/XML/1998/namespace}space"
    digest = hashlib.sha256()

    def add(value: str) -> None:
        encoded = value.encode("utf-8", errors="strict")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)

    def walk(node: Element) -> None:
        add(node.tag)
        attributes = sorted(
            (name, value)
            for name, value in node.attrib.items()
            if not (id(node) in ignored and name == space)
        )
        add(str(len(attributes)))
        for name, value in attributes:
            add(name)
            add(value)
        text = node.text or ""
        add(text if local_name(node.tag) == "t" or text.strip() else "")
        children = list(node)
        add(str(len(children)))
        for child in children:
            walk(child)
            tail = child.tail or ""
            add(tail if tail.strip() else "")

    walk(root)
    return digest.hexdigest()


def _text_descendants(node: Element) -> list[str]:
    return [
        child.text or ""
        for child in node.iter()
        if local_name(child.tag) in {"delText", "instrText", "t"}
    ]


def _value(node: Element | None) -> str | None:
    return node.attrib.get(qn("w", "val")) if node is not None else None
