import json
from pathlib import Path
import shutil
import subprocess

from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS

from document_skills_core.core.io.paths import sha256_file


def _public(project_root: Path, *args: str) -> dict[str, object]:
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
        check=True,
        timeout=PUBLIC_CLI_TEST_TIMEOUT_SECONDS,
    )
    return json.loads(completed.stdout)


def _request(directory: Path, name: str, payload: dict[str, object]) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _create_with_note(
    project_root: Path,
    tmp_path: Path,
    *,
    name: str,
    paragraph_text: str,
    note_text: str,
    kind: str,
) -> Path:
    plain = tmp_path / f"{name}-plain.docx"
    create = _request(
        tmp_path,
        f"{name}-create.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(plain),
            "arguments": {
                "report": {
                    "blocks": [{"type": "paragraph", "text": paragraph_text}]
                }
            },
        },
    )
    created = _public(project_root, "run", "--request", str(create))
    assert created["status"] == "success", created
    output = tmp_path / f"{name}.docx"
    edit = _request(
        tmp_path,
        f"{name}-note.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(plain),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "note_insert",
                        "target": {
                            "story": "body",
                            "paragraph_index": 0,
                            "expected_text": paragraph_text,
                        },
                        "kind": kind,
                        "placement": "append",
                        "text": note_text,
                    }
                ]
            },
        },
    )
    edited = _public(project_root, "run", "--request", str(edit))
    assert edited["status"] == "success", edited
    return output


def test_public_merge_remaps_colliding_footnote_ids_and_preserves_notes(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base = _create_with_note(
        project_root,
        tmp_path,
        name="note-merge-base",
        paragraph_text="Base",
        note_text="Base footnote",
        kind="footnote",
    )
    source = _create_with_note(
        project_root,
        tmp_path,
        name="note-merge-source",
        paragraph_text="Source",
        note_text="Source footnote",
        kind="footnote",
    )
    base_sha256 = sha256_file(base)
    source_sha256 = sha256_file(source)
    output = tmp_path / "notes-merged.docx"
    merge = _request(
        tmp_path,
        "notes-merge.json",
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

    result = _public(project_root, "run", "--request", str(merge))

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]["merge"]
    assert operation["note_mappings"] == [
        {
            "kind": "footnote",
            "source_id": "1",
            "source_index": 1,
            "target_id": "2",
        }
    ]
    assert operation["preserved_notes"] == 2
    read = _request(
        tmp_path,
        "notes-merged-read.json",
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(output),
            "arguments": {},
        },
    )
    document = _public(project_root, "run", "--request", str(read))
    assert document["status"] == "success", document
    assert document["diagnostics"]["operation_result"]["document"]["notes"] == [
        {
            "kind": "footnote",
            "id": "1",
            "text": "Base footnote",
            "reference_count": 1,
        },
        {
            "kind": "footnote",
            "id": "2",
            "text": "Source footnote",
            "reference_count": 1,
        },
    ]
    assert sha256_file(base) == base_sha256
    assert sha256_file(source) == source_sha256


def test_public_merge_adds_missing_endnote_part_and_relationship(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base = _create_with_note(
        project_root,
        tmp_path,
        name="endnote-merge-base",
        paragraph_text="Base",
        note_text="Base footnote",
        kind="footnote",
    )
    source = _create_with_note(
        project_root,
        tmp_path,
        name="endnote-merge-source",
        paragraph_text="Source",
        note_text="Source endnote",
        kind="endnote",
    )
    source_sha256 = sha256_file(source)
    output = tmp_path / "endnotes-merged.docx"
    merge = _request(
        tmp_path,
        "endnotes-merge.json",
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

    result = _public(project_root, "run", "--request", str(merge))

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["merge"]["note_mappings"] == [
        {
            "kind": "endnote",
            "source_id": "1",
            "source_index": 1,
            "target_id": "1",
        }
    ]
    assert "word/endnotes.xml" in operation_result["preservation"]["added_parts"]
    read = _request(
        tmp_path,
        "endnotes-merged-read.json",
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(output),
            "arguments": {},
        },
    )
    document = _public(project_root, "run", "--request", str(read))
    assert document["status"] == "success", document
    notes = document["diagnostics"]["operation_result"]["document"]["notes"]
    assert notes == [
        {
            "kind": "footnote",
            "id": "1",
            "text": "Base footnote",
            "reference_count": 1,
        },
        {
            "kind": "endnote",
            "id": "1",
            "text": "Source endnote",
            "reference_count": 1,
        },
    ]
