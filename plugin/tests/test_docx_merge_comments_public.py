import json
from pathlib import Path
import shutil
import subprocess
from xml.etree.ElementTree import Element, fromstring, SubElement, tostring
import zipfile

from document_skills_core.core.io.paths import sha256_file
from document_skills_core.formats.docx.constants import (
    CONTENT_TYPES_NS,
    CT_COMMENTS,
    REL_COMMENTS,
    qn,
)


def _public(
    project_root: Path,
    *args: str,
    check: bool = True,
) -> dict[str, object]:
    completed = subprocess.run(
        [
            shutil.which("uv"),
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills" / "document-docx" / "scripts" / "run.py"),
            *args,
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=check,
        timeout=60,
    )
    return json.loads(completed.stdout)


def _request(directory: Path, name: str, payload: dict[str, object]) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _create_document(
    project_root: Path,
    tmp_path: Path,
    *,
    name: str,
    text: str,
) -> Path:
    output = tmp_path / f"{name}-plain.docx"
    request = _request(
        tmp_path,
        f"{name}-create.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "report": {"blocks": [{"type": "paragraph", "text": text}]}
            },
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] == "success", result
    return output


def _add_comment(
    source: Path,
    destination: Path,
    *,
    author: str,
    comment_text: str,
    extended: bool = False,
) -> None:
    with zipfile.ZipFile(source) as archive:
        parts = {item.filename: archive.read(item) for item in archive.infolist()}
    document = fromstring(parts["word/document.xml"])
    paragraph = next(document.iter(qn("w", "p")))
    first_content = next(
        (child for child in paragraph if child.tag != qn("w", "pPr")),
        None,
    )
    start = Element(qn("w", "commentRangeStart"), {qn("w", "id"): "0"})
    if first_content is None:
        paragraph.append(start)
    else:
        paragraph.insert(list(paragraph).index(first_content), start)
    paragraph.append(Element(qn("w", "commentRangeEnd"), {qn("w", "id"): "0"}))
    reference_run = SubElement(paragraph, qn("w", "r"))
    SubElement(reference_run, qn("w", "commentReference"), {qn("w", "id"): "0"})
    comments = Element(qn("w", "comments"))
    comment = SubElement(
        comments,
        qn("w", "comment"),
        {
            qn("w", "id"): "0",
            qn("w", "author"): author,
            qn("w", "date"): "2026-08-24T00:00:00Z",
        },
    )
    comment_paragraph = SubElement(comment, qn("w", "p"))
    run = SubElement(comment_paragraph, qn("w", "r"))
    text = SubElement(run, qn("w", "t"))
    text.text = comment_text
    relationships = fromstring(parts["word/_rels/document.xml.rels"])
    SubElement(
        relationships,
        qn("rels", "Relationship"),
        {
            "Id": "rIdComments",
            "Type": REL_COMMENTS,
            "Target": "comments.xml",
        },
    )
    content_types = fromstring(parts["[Content_Types].xml"])
    SubElement(
        content_types,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {"PartName": "/word/comments.xml", "ContentType": CT_COMMENTS},
    )
    if extended:
        SubElement(
            content_types,
            f"{{{CONTENT_TYPES_NS}}}Override",
            {
                "PartName": "/word/commentsExtended.xml",
                "ContentType": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.commentsExtended+xml"
                ),
            },
        )
        parts["word/commentsExtended.xml"] = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<w15:commentsEx xmlns:w15="http://schemas.microsoft.com/'
            b'office/word/2012/wordml"/>'
        )
    parts.update(
        {
            "[Content_Types].xml": tostring(
                content_types,
                encoding="utf-8",
                xml_declaration=True,
            ),
            "word/_rels/document.xml.rels": tostring(
                relationships,
                encoding="utf-8",
                xml_declaration=True,
            ),
            "word/comments.xml": tostring(
                comments,
                encoding="utf-8",
                xml_declaration=True,
            ),
            "word/document.xml": tostring(
                document,
                encoding="utf-8",
                xml_declaration=True,
            ),
        }
    )
    with zipfile.ZipFile(destination, "w") as archive:
        for name, payload in sorted(parts.items()):
            archive.writestr(name, payload)


def test_public_merge_remaps_colliding_comment_ids_and_preserves_ranges(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base_plain = _create_document(
        project_root,
        tmp_path,
        name="comment-merge-base",
        text="Base",
    )
    source_plain = _create_document(
        project_root,
        tmp_path,
        name="comment-merge-source",
        text="Source",
    )
    base = tmp_path / "comment-merge-base.docx"
    source = tmp_path / "comment-merge-source.docx"
    _add_comment(base_plain, base, author="Base reviewer", comment_text="Base comment")
    _add_comment(source_plain, source, author="Source reviewer", comment_text="Source comment")
    base_sha256 = sha256_file(base)
    source_sha256 = sha256_file(source)
    output = tmp_path / "comments-merged.docx"
    request = _request(
        tmp_path,
        "comments-merge.json",
        {
            "schema_version": "1.0",
            "operation": "docx.merge",
            "input": str(base),
            "output": str(output),
            "arguments": {
                "sources": [
                    {"path": str(source), "expected_sha256": source_sha256}
                ],
                "style_conflict_policy": "require-identical",
                "numbering_conflict_policy": "require-identical",
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    merge = result["diagnostics"]["operation_result"]["merge"]
    assert merge["comment_mappings"] == [
        {"source_id": "0", "source_index": 1, "target_id": "1"}
    ]
    assert merge["preserved_comments"] == 2
    with zipfile.ZipFile(output) as archive:
        document = fromstring(archive.read("word/document.xml"))
        comments = fromstring(archive.read("word/comments.xml"))
    assert [
        comment.attrib[qn("w", "id")]
        for comment in comments.findall(qn("w", "comment"))
    ] == ["0", "1"]
    assert ["".join(comment.itertext()) for comment in comments] == [
        "Base comment",
        "Source comment",
    ]
    for local in ("commentRangeStart", "commentRangeEnd", "commentReference"):
        assert {
            node.attrib[qn("w", "id")]
            for node in document.iter(qn("w", local))
        } == {"0", "1"}
    assert sha256_file(base) == base_sha256
    assert sha256_file(source) == source_sha256


def test_public_merge_rejects_threaded_comment_parts_without_publishing(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base = _create_document(
        project_root,
        tmp_path,
        name="threaded-comment-base",
        text="Base",
    )
    source_plain = _create_document(
        project_root,
        tmp_path,
        name="threaded-comment-source",
        text="Source",
    )
    source = tmp_path / "threaded-comment-source.docx"
    _add_comment(
        source_plain,
        source,
        author="Reviewer",
        comment_text="Thread root",
        extended=True,
    )
    source_sha256 = sha256_file(source)
    base_sha256 = sha256_file(base)
    output = tmp_path / "threaded-comments-merged.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "threaded-comments-merge.json",
        {
            "schema_version": "1.0",
            "operation": "docx.merge",
            "input": str(base),
            "output": str(output),
            "arguments": {
                "sources": [
                    {"path": str(source), "expected_sha256": source_sha256}
                ],
                "style_conflict_policy": "require-identical",
                "numbering_conflict_policy": "require-identical",
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "enhancement_required", result
    error = result["errors"][0]
    assert error["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert error["details"]["parts"] == ["word/commentsExtended.xml"]
    assert output.read_bytes() == original_destination
    assert sha256_file(base) == base_sha256
    assert sha256_file(source) == source_sha256
