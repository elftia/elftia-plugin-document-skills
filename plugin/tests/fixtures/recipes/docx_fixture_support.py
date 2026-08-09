"""Original Elftia helpers for deterministic benign and protected DOCX fixtures."""

from pathlib import Path
from xml.etree.ElementTree import Element, SubElement
import zipfile

from document_skills_core.formats.docx.constants import REL_HYPERLINK, qn
from document_skills_core.formats.docx.package import OpcPackage
from document_skills_core.formats.docx.xml_utils import set_text, xml_bytes

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02\x00\x00\x00\x0bIDATx\xdac`\xf8"
    b"\x0f\x00\x01\x05\x01\x01'\x18\xe3f\x00\x00\x00\x00IEND\xaeB`\x82"
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
REGULAR_ZIP_MODE = 0o100644 << 16


def report_model(image: Path) -> dict[str, object]:
    """Return the bounded report model used as the deterministic rich base."""

    return {
        "metadata": {
            "title": "Elftia DOCX acceptance",
            "subject": "Original deterministic fixture",
            "creator": "Elftia",
            "keywords": "docx,acceptance",
        },
        "blocks": [
            {"type": "heading", "text": "Core DOCX", "level": 1},
            {
                "type": "paragraph",
                "text": "Template {customer.name} and {region}; Replace TARGET.",
                "style": None,
            },
            {
                "type": "table",
                "style": "TableGrid",
                "rows": [["Location", "Value"], ["Table", "TARGET"]],
            },
        ],
        "image": {"path": image, "alt_text": "Elftia pixel", "width_inches": 1.0},
        "header": "Header TARGET",
        "footer": "Footer TARGET",
        "sections": [
            {"orientation": "portrait", "title": "First"},
            {"orientation": "landscape", "title": "Second"},
        ],
    }


def enrich_rich(path: Path) -> None:
    """Add deterministic split runs, list, and hyperlink to a created DOCX."""

    package = OpcPackage.open(path)
    document = package.xml("word/document.xml")
    body = document.find(qn("w", "body"))
    assert body is not None

    template = _paragraph_containing(body, "Template")
    _set_runs(
        template,
        [
            ("Template {customer.", True, False),
            ("name}", False, True),
            (" and {region}; Replace TA", False, False),
            ("RGET.", False, True),
        ],
    )

    table_target = _paragraph_with_exact_text(body, "TARGET")
    _set_runs(
        table_target,
        [("TA", True, False), ("RGET", False, True)],
    )

    normal_token = _paragraph("Normal placeholder {normal}")
    overlap = _paragraph("Overlap AAAA")
    body.insert(max(len(body) - 1, 0), normal_token)
    body.insert(max(len(body) - 1, 0), overlap)

    list_paragraph = Element(qn("w", "p"))
    paragraph_properties = SubElement(list_paragraph, qn("w", "pPr"))
    numbering = SubElement(paragraph_properties, qn("w", "numPr"))
    SubElement(numbering, qn("w", "ilvl"), {qn("w", "val"): "0"})
    SubElement(numbering, qn("w", "numId"), {qn("w", "val"): "1"})
    _run(list_paragraph, "List item")
    body.insert(max(len(body) - 1, 0), list_paragraph)

    hyperlink = Element(qn("w", "p"))
    link = SubElement(
        hyperlink,
        qn("w", "hyperlink"),
        {qn("r", "id"): "rIdInternalLink"},
    )
    _run(link, "Internal reference")
    body.insert(max(len(body) - 1, 0), hyperlink)

    relationships = package.xml("word/_rels/document.xml.rels")
    SubElement(
        relationships,
        qn("rels", "Relationship"),
        {
            "Id": "rIdInternalLink",
            "Type": REL_HYPERLINK,
            "Target": "bookmarks.xml",
        },
    )

    header = package.xml("word/header1.xml")
    _set_runs(
        _paragraph_containing(header, "Header"),
        [
            ("Header ", False, False),
            ("TA", True, False),
            ("RGET", False, True),
        ],
    )
    footer = package.xml("word/footer1.xml")
    _set_runs(
        _paragraph_containing(footer, "Footer"),
        [
            ("Footer ", False, False),
            ("TA", True, False),
            ("RGET", False, True),
        ],
    )

    temporary = path.with_suffix(".tmp.docx")
    package.write_copy(
        temporary,
        changed_parts={
            "word/document.xml": xml_bytes(document),
            "word/_rels/document.xml.rels": xml_bytes(relationships),
            "word/header1.xml": xml_bytes(header),
            "word/footer1.xml": xml_bytes(footer),
        },
        added_parts={
            "word/bookmarks.xml": (
                b'<?xml version="1.0"?><bookmarks xmlns="urn:elftia"/>'
            )
        },
    )
    temporary.replace(path)


def revision_fixture(source: Path, destination: Path) -> None:
    """Create protected revision, deletion, field, and comment text cases."""

    package = OpcPackage.open(source)
    document = package.xml("word/document.xml")
    body = document.find(qn("w", "body"))
    assert body is not None
    paragraph = Element(qn("w", "p"))
    inserted = SubElement(paragraph, qn("w", "ins"))
    _run(inserted, "revision-only {protected.revision}")
    deleted = SubElement(paragraph, qn("w", "del"))
    deleted_run = SubElement(deleted, qn("w", "r"))
    SubElement(deleted_run, qn("w", "delText")).text = (
        "deleted-only {protected.deleted}"
    )
    field = SubElement(
        paragraph,
        qn("w", "fldSimple"),
        {qn("w", "instr"): "MERGEFIELD protected"},
    )
    _run(field, "field-only {protected.field}")
    body.insert(max(len(body) - 1, 0), paragraph)

    comments = Element(qn("w", "comments"))
    comment = SubElement(comments, qn("w", "comment"), {qn("w", "id"): "0"})
    comment.append(_paragraph("comment-only {protected.comment}"))
    package.write_copy(
        destination,
        changed_parts={"word/document.xml": xml_bytes(document)},
        added_parts={"word/comments.xml": xml_bytes(comments)},
    )


def copy_with_additions(
    source: Path,
    destination: Path,
    additions: dict[str, bytes],
) -> None:
    package_parts = parts(source)
    package_parts.update(additions)
    write_entries(destination, sorted(package_parts.items()))


def parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {
            name: archive.read(name)
            for name in archive.namelist()
            if not name.endswith("/")
        }


def write_entries(
    destination: Path,
    entries: list[tuple[str, bytes]],
    *,
    modes: dict[str, int] | None = None,
) -> None:
    """Write a fixed-order, fixed-metadata ZIP, including deliberate duplicates."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    entry_modes = modes or {}
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name, payload in entries:
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = entry_modes.get(name, REGULAR_ZIP_MODE)
            archive.writestr(info, payload)


def _paragraph_containing(root: Element, marker: str) -> Element:
    return next(
        paragraph
        for paragraph in root.iter(qn("w", "p"))
        if marker
        in "".join(node.text or "" for node in paragraph.iter(qn("w", "t")))
    )


def _paragraph_with_exact_text(root: Element, text: str) -> Element:
    return next(
        paragraph
        for paragraph in root.iter(qn("w", "p"))
        if text
        == "".join(node.text or "" for node in paragraph.iter(qn("w", "t")))
    )


def _set_runs(
    paragraph: Element,
    segments: list[tuple[str, bool, bool]],
) -> None:
    properties = paragraph.find(qn("w", "pPr"))
    for child in list(paragraph):
        if child is not properties:
            paragraph.remove(child)
    for text, bold, italic in segments:
        _run(paragraph, text, bold=bold, italic=italic)


def _run(
    parent: Element,
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
) -> None:
    run = SubElement(parent, qn("w", "r"))
    if bold or italic:
        properties = SubElement(run, qn("w", "rPr"))
        if bold:
            SubElement(properties, qn("w", "b"))
        if italic:
            SubElement(properties, qn("w", "i"))
    node = SubElement(run, qn("w", "t"))
    set_text(node, text)


def _paragraph(text: str) -> Element:
    paragraph = Element(qn("w", "p"))
    _run(paragraph, text)
    return paragraph
