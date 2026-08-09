"""Required create-semantics gate: the checks the optional-content change added.

Making tables, images, stories and sections optional — and letting image blocks
sit anywhere in the block list — gave the emitter degrees of freedom the gate
never had to police before. Each test here doctors a package that `create_docx`
produced and asserts the gate refuses to promote it.
"""

from pathlib import Path
import struct
from xml.etree.ElementTree import Element, SubElement
import zlib

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.docx.constants import CONTENT_TYPES_NS, CT_HEADER, qn
from document_skills_core.formats.docx.create import create_docx
from document_skills_core.formats.docx.package import OpcPackage
from document_skills_core.formats.docx.validation import _assert_created
from document_skills_core.formats.docx.xml_utils import xml_bytes

from tests.fixtures.recipes.docx_fixture_support import PNG_1X1

_GIF_1X1 = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


def _png(width: int, height: int) -> bytes:
    """A minimal valid RGBA PNG, so payload-identity tests use real bytes."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _image(path: Path, alt: str) -> dict[str, object]:
    return {"path": path, "alt_text": alt, "width_inches": 1.0}


def _report(**overrides: object) -> dict[str, object]:
    report: dict[str, object] = {
        "blocks": [{"type": "paragraph", "text": "Body", "style": None}],
        "image": None,
        "header": None,
        "footer": None,
        "sections": [{"orientation": "portrait", "title": None}],
        "metadata": {"title": "", "subject": "", "creator": "", "keywords": ""},
    }
    report.update(overrides)
    return report


def _built(
    tmp_path: Path,
    report: dict[str, object],
    name: str = "out.docx",
) -> tuple[Path, list[dict[str, object]]]:
    """Build a package and return it with the creation image oracle."""

    path = tmp_path / name
    creation = create_docx(path, report)
    images = creation["images"]
    _assert_created(path, report, images)  # the untouched package must pass
    return path, images


def _rewrite(
    path: Path,
    *,
    changed_parts: dict[str, bytes] | None = None,
    added_parts: dict[str, bytes] | None = None,
) -> Path:
    package = OpcPackage.open(path)
    destination = path.with_name(f"doctored-{path.name}")
    package.write_copy(
        destination,
        changed_parts=changed_parts or {},
        added_parts=added_parts or {},
    )
    return destination


def _failures(
    report: dict[str, object],
    path: Path,
    images: list[dict[str, object]],
) -> list[str]:
    with pytest.raises(DocumentSkillsError) as captured:
        _assert_created(path, report, images)
    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    details = captured.value.details or {}
    return list(details.get("missing_or_mismatched", []))


def test_multiple_images_get_distinct_non_visual_drawing_ids(tmp_path: Path) -> None:
    png = tmp_path / "a.png"
    png.write_bytes(PNG_1X1)
    gif = tmp_path / "b.gif"
    gif.write_bytes(_GIF_1X1)
    report = _report(
        blocks=[
            {"type": "image", **_image(png, "one")},
            {"type": "paragraph", "text": "between", "style": None},
            {"type": "image", **_image(gif, "two")},
        ]
    )
    path, images = _built(tmp_path, report)

    document = OpcPackage.open(path).xml("word/document.xml")
    ids = [
        node.attrib.get("id")
        for node in document.iter(qn("pic", "cNvPr"))
    ]
    assert ids == ["0", "1"]
    embeds = [
        node.attrib.get(qn("r", "embed")) for node in document.iter(qn("a", "blip"))
    ]
    assert embeds == ["rIdImage1", "rIdImage2"]


def test_gate_rejects_an_image_moved_out_of_its_requested_position(
    tmp_path: Path,
) -> None:
    png = tmp_path / "a.png"
    png.write_bytes(PNG_1X1)
    report = _report(
        blocks=[
            {"type": "paragraph", "text": "before", "style": None},
            {"type": "image", **_image(png, "figure")},
            {"type": "paragraph", "text": "after", "style": None},
        ]
    )
    path, images = _built(tmp_path, report)

    package = OpcPackage.open(path)
    document = package.xml("word/document.xml")
    body = document.find(qn("w", "body"))
    assert body is not None
    drawing_paragraph = next(
        child
        for child in body
        if child.tag == qn("w", "p")
        and child.find(f".//{qn('w', 'drawing')}") is not None
    )
    body.remove(drawing_paragraph)
    body.insert(0, drawing_paragraph)  # same image, wrong place
    doctored = _rewrite(path, changed_parts={"word/document.xml": xml_bytes(document)})

    assert "block-layout" in _failures(report, doctored, images)


def test_gate_rejects_a_story_part_the_request_did_not_ask_for(
    tmp_path: Path,
) -> None:
    report = _report()
    path, images = _built(tmp_path, report)

    orphan = Element(qn("w", "hdr"))
    SubElement(orphan, qn("w", "p"))
    doctored = _rewrite(path, added_parts={"word/header1.xml": xml_bytes(orphan)})

    # Unreferenced, so `document_stories` cannot see it — only the exact
    # part-set assertion catches this one.
    assert "package-parts" in _failures(report, doctored, images)


def test_gate_rejects_heading_styles_the_document_never_uses(
    tmp_path: Path,
) -> None:
    report = _report(blocks=[{"type": "heading", "text": "Title", "level": 1}])
    path, images = _built(tmp_path, report)

    package = OpcPackage.open(path)
    styles = package.xml("word/styles.xml")
    extra = SubElement(
        styles,
        qn("w", "style"),
        {qn("w", "type"): "paragraph", qn("w", "styleId"): "Heading6"},
    )
    SubElement(extra, qn("w", "name"), {qn("w", "val"): "heading 6"})
    doctored = _rewrite(path, changed_parts={"word/styles.xml": xml_bytes(styles)})

    assert "styles" in _failures(report, doctored, images)


def test_gate_still_rejects_a_missing_heading_style(tmp_path: Path) -> None:
    report = _report(blocks=[{"type": "heading", "text": "Deep", "level": 4}])
    path, images = _built(tmp_path, report)

    package = OpcPackage.open(path)
    styles = package.xml("word/styles.xml")
    doomed = next(
        node
        for node in styles.findall(qn("w", "style"))
        if node.attrib.get(qn("w", "styleId")) == "Heading3"
    )
    styles.remove(doomed)
    doctored = _rewrite(path, changed_parts={"word/styles.xml": xml_bytes(styles)})

    assert "styles" in _failures(report, doctored, images)


def test_gate_rejects_swapped_image_payloads(tmp_path: Path) -> None:
    """Same format, same alt text order — only the bytes moved."""

    first = tmp_path / "a.png"
    first.write_bytes(PNG_1X1)
    second = tmp_path / "b.png"
    second.write_bytes(_png(2, 1))
    assert second.read_bytes() != PNG_1X1
    report = _report(
        blocks=[
            {"type": "image", **_image(first, "one")},
            {"type": "image", **_image(second, "two")},
        ]
    )
    path, images = _built(tmp_path, report)

    package = OpcPackage.open(path)
    document = package.xml("word/document.xml")
    blips = list(document.iter(qn("a", "blip")))
    assert len(blips) == 2
    embed = qn("r", "embed")
    blips[0].set(embed, "rIdImage2")
    blips[1].set(embed, "rIdImage1")
    doctored = _rewrite(path, changed_parts={"word/document.xml": xml_bytes(document)})

    assert "image-relationship-type" in _failures(report, doctored, images)


def test_gate_rejects_a_story_part_hidden_behind_an_innocent_name(
    tmp_path: Path,
) -> None:
    """OPC part names carry no guarantee — the inventory goes by content type."""

    report = _report()
    path, images = _built(tmp_path, report)

    package = OpcPackage.open(path)
    ghost = Element(qn("w", "hdr"))
    SubElement(ghost, qn("w", "p"))
    types = package.xml("[Content_Types].xml")
    SubElement(
        types,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {"PartName": "/word/ghost.xml", "ContentType": CT_HEADER},
    )
    doctored = _rewrite(
        path,
        changed_parts={"[Content_Types].xml": xml_bytes(types)},
        added_parts={"word/ghost.xml": xml_bytes(ghost)},
    )

    assert "package-parts" in _failures(report, doctored, images)


def test_gate_does_not_re_read_the_source_after_creation(tmp_path: Path) -> None:
    """The oracle is the creation snapshot, not the caller's mutable path.

    Re-reading would let a source replaced between creation and validation fail
    a package that was built correctly — a false failure that blocks promotion.
    """

    source = tmp_path / "a.png"
    source.write_bytes(PNG_1X1)
    report = _report(blocks=[{"type": "image", **_image(source, "figure")}])
    path, images = _built(tmp_path, report)

    replacement = _png(4, 2)
    assert replacement != PNG_1X1
    source.write_bytes(replacement)

    # Same format, different bytes, still a valid image: the untouched package
    # must still pass.
    _assert_created(path, report, images)

    source.unlink()
    _assert_created(path, report, images)


def test_creation_result_keeps_the_single_image_member(tmp_path: Path) -> None:
    png = tmp_path / "a.png"
    png.write_bytes(PNG_1X1)
    report = _report(image=_image(png, "trailing"))
    creation = create_docx(tmp_path / "compat.docx", report)

    assert creation["image"] == creation["images"][0]
    assert creation["image"]["extension"] == "png"


def test_creation_result_image_member_is_none_without_images(tmp_path: Path) -> None:
    creation = create_docx(tmp_path / "plain.docx", _report())

    assert creation["images"] == []
    assert creation["image"] is None
