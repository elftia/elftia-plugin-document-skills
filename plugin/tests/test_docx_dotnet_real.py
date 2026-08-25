"""Real .NET 8/OpenXML profile through the public DOCX façade."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from document_skills_core.core.io.paths import sha256_file
from document_skills_core.formats.docx.validation import reopen_docx


def _public(project_root: Path, *arguments: str) -> dict[str, object]:
    completed = subprocess.run(
        [
            shutil.which("uv"),
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-docx/scripts/run.py"),
            *arguments,
        ],
        cwd=project_root,
        capture_output=True,
        text=False,
        check=False,
        timeout=120,
    )
    assert completed.stderr == b""
    payload = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    assert type(payload) is dict
    return payload


def _request(tmp_path: Path, name: str, payload: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _run(
    project_root: Path,
    tmp_path: Path,
    name: str,
    payload: dict[str, object],
) -> dict[str, object]:
    request = _request(tmp_path, name, payload)
    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] == "success", result
    assert result["provider_chain"] == ["dotnet-openxml"]
    return result


def _require_dotnet_profile(project_root: Path) -> None:
    capabilities = _public(project_root, "capabilities", "--json")
    provider = next(
        item
        for item in capabilities["providers"]
        if item["id"] == "dotnet-openxml"
    )
    required = os.environ.get("ELFTIA_REQUIRE_DOTNET_PROFILE") == "1"
    if required:
        assert provider["available"] is True, provider
        assert provider["version"].startswith("3.0.0")
    elif provider["available"] is not True:
        pytest.skip("real .NET 8/OpenXML profile is unavailable")


@pytest.mark.skipif(os.name != "nt", reason="HKCU Environment is Windows-only")
def test_real_dotnet_detection_does_not_mutate_user_path(
    project_root: Path,
) -> None:
    import winreg

    def user_path() -> tuple[str, int] | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value, registry_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return None
        return str(value), registry_type

    before = user_path()
    try:
        _require_dotnet_profile(project_root)
    finally:
        assert user_path() == before


def test_real_dotnet_profile_runs_every_public_operation(
    project_root: Path,
    tmp_path: Path,
) -> None:
    _require_dotnet_profile(project_root)
    revision_source = project_root / "tests/fixtures/docx-revisions-nested.docx"
    revision_sha256 = sha256_file(revision_source)
    revision_scope = {
        "story": "body",
        "range": "table",
        "table_index": 1,
        "expected_table_sha256": (
            "05863db08075a5cbbc625625b0e0f5540"
            "b027e3c6ce23067b7cd6586c0518ae4"
        ),
    }
    revision_filters = {"authors": ["Carol"], "types": ["insertion"]}
    revisions = _run(
        project_root,
        tmp_path,
        "real-revisions-read.json",
        {
            "schema_version": "1.0",
            "operation": "docx.revisions.read",
            "input": str(revision_source),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "max_revisions": 100,
                "filters": revision_filters,
                "scope": revision_scope,
            },
        },
    )
    items = revisions["diagnostics"]["operation_result"]["revisions"]["items"]
    assert len(items) == 1
    revision_id = items[0]["id"]

    accepted = tmp_path / "real-revision-accepted.docx"
    applied = _run(
        project_root,
        tmp_path,
        "real-revisions-apply.json",
        {
            "schema_version": "1.0",
            "operation": "docx.revisions.apply",
            "input": str(revision_source),
            "output": str(accepted),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "action": "accept",
                "revision_ids": [revision_id],
                "filters": revision_filters,
                "scope": revision_scope,
            },
        },
    )
    assert applied["diagnostics"]["operation_result"]["revisions"][
        "matched_ids"
    ] == [revision_id]
    assert reopen_docx(accepted)["parts"] >= 3
    assert sha256_file(revision_source) == revision_sha256

    comment_source = project_root / "tests/fixtures/docx-revision-comments.docx"
    comment_sha256 = sha256_file(comment_source)
    comments = _run(
        project_root,
        tmp_path,
        "real-comments-read.json",
        {
            "schema_version": "1.0",
            "operation": "docx.comments.read",
            "input": str(comment_source),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_comments": 100},
        },
    )
    assert comments["diagnostics"]["operation_result"]["comments"]["items"]

    commented = tmp_path / "real-comment-added.docx"
    added = _run(
        project_root,
        tmp_path,
        "real-comments-add.json",
        {
            "schema_version": "1.0",
            "operation": "docx.comments.add",
            "input": str(comment_source),
            "output": str(commented),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "author": "Real Profile",
                "text": "Public OpenXML comment",
                "anchor": {
                    "story": "body",
                    "paragraph_index": 0,
                    "expected_text": "Core DOCX",
                    "range": "paragraph",
                },
            },
        },
    )
    assert added["diagnostics"]["operation_result"]["comment"]["author"] == (
        "Real Profile"
    )
    assert reopen_docx(commented)["parts"] >= 3
    assert sha256_file(comment_source) == comment_sha256

    schema = _run(
        project_root,
        tmp_path,
        "real-schema.json",
        {
            "schema_version": "1.0",
            "operation": "docx.validate.schema",
            "input": str(commented),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_errors": 100},
        },
    )
    schema_result = schema["diagnostics"]["operation_result"]["schema"]
    assert schema_result["valid"] is True
    schema_gate = next(
        gate
        for gate in schema["validation"]["gates"]
        if gate["id"] == "schema.full"
    )
    assert schema_gate["outcome"] == "pass"
    assert schema_gate["validator"] == "dotnet-openxml"

    helper_root = (
        project_root
        / "src/document_skills_core/providers/dotnet/helper"
    )
    forbidden_generated_roots = [
        project_root / "NuGet",
        helper_root / "bin",
        helper_root / "NuGet",
        helper_root / "obj",
    ]
    assert not [path for path in forbidden_generated_roots if path.exists()]


def test_real_dotnet_profile_round_trips_comment_threads_and_resolution(
    project_root: Path,
    tmp_path: Path,
) -> None:
    _require_dotnet_profile(project_root)
    source = project_root / "tests/fixtures/docx-public-bounded-word16-accepted.docx"
    source_sha256 = sha256_file(source)
    anchor = {
        "story": "body",
        "paragraph_index": 0,
        "expected_text": "Bounded public DOCX",
        "range": "paragraph",
    }

    rooted_path = tmp_path / "real-comment-thread-root.docx"
    rooted = _run(
        project_root,
        tmp_path,
        "real-comment-thread-root.json",
        {
            "schema_version": "1.0",
            "operation": "docx.comments.add",
            "input": str(source),
            "output": str(rooted_path),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "author": "Thread Root",
                "text": "Root comment",
                "anchor": anchor,
            },
        },
    )
    root = rooted["diagnostics"]["operation_result"]["comment"]
    root_id = root["id"]
    assert root["parent_comment_id"] is None
    assert root["thread_id"] == root_id
    assert root["resolved"] is False

    replied_path = tmp_path / "real-comment-thread-reply.docx"
    replied = _run(
        project_root,
        tmp_path,
        "real-comment-thread-reply.json",
        {
            "schema_version": "1.0",
            "operation": "docx.comments.add",
            "input": str(rooted_path),
            "output": str(replied_path),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "author": "Thread Reply",
                "text": "Reply comment",
                "parent_comment_id": root_id,
            },
        },
    )
    reply = replied["diagnostics"]["operation_result"]["comment"]
    assert reply["parent_comment_id"] == root_id
    assert reply["thread_id"] == root_id
    assert reply["resolved"] is False

    resolved_path = tmp_path / "real-comment-thread-resolved.docx"
    resolved = _run(
        project_root,
        tmp_path,
        "real-comment-thread-resolve.json",
        {
            "schema_version": "1.0",
            "operation": "docx.comments.resolve",
            "input": str(replied_path),
            "output": str(resolved_path),
            "options": {"fidelity": "enhanced"},
            "arguments": {"comment_id": root_id, "resolved": True},
        },
    )
    resolved_root = resolved["diagnostics"]["operation_result"]["comment"]
    assert resolved_root["id"] == root_id
    assert resolved_root["resolved"] is True

    read_back = _run(
        project_root,
        tmp_path,
        "real-comment-thread-read.json",
        {
            "schema_version": "1.0",
            "operation": "docx.comments.read",
            "input": str(resolved_path),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_comments": 10},
        },
    )
    items = read_back["diagnostics"]["operation_result"]["comments"]["items"]
    root_item = next(item for item in items if item["id"] == root_id)
    reply_item = next(item for item in items if item["id"] == reply["id"])
    assert root_item["parent_comment_id"] is None
    assert root_item["thread_id"] == root_id
    assert root_item["resolved"] is True
    assert reply_item["parent_comment_id"] == root_id
    assert reply_item["thread_id"] == root_id
    assert reply_item["resolved"] is True
    assert root_item["anchor"] == reply_item["anchor"] == {
        "story": "body",
        "paragraph_index": 0,
        "range": "paragraph",
    }
    schema = _run(
        project_root,
        tmp_path,
        "real-comment-thread-schema.json",
        {
            "schema_version": "1.0",
            "operation": "docx.validate.schema",
            "input": str(resolved_path),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_errors": 100},
        },
    )
    assert schema["diagnostics"]["operation_result"]["schema"] == {
        "valid": True,
        "errors": [],
        "returned_errors": 0,
        "truncated": False,
    }
    assert reopen_docx(resolved_path)["parts"] >= 3
    assert sha256_file(source) == source_sha256


def test_real_openxml_validator_accepts_academic_references_and_omml(
    project_root: Path,
    tmp_path: Path,
) -> None:
    _require_dotnet_profile(project_root)
    output = tmp_path / "real-academic-openxml.docx"
    create_request = _request(
        tmp_path,
        "real-academic-create.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "document_spec": {
                    "version": "1.0",
                    "domain_profile": {
                        "id": "academic-paper",
                        "version": "1.0",
                        "locale": "en-US",
                        "citation_style": "author-year",
                    },
                    "style_profile": {
                        "id": "professional-generic",
                        "version": "1.0",
                    },
                    "nodes": [
                        {
                            "id": "paper_title",
                            "type": "title",
                            "text": "OpenXML Evidence",
                        },
                        {
                            "id": "paper_authors",
                            "type": "authors",
                            "items": ["Ada Lovelace"],
                        },
                        {
                            "id": "paper_abstract",
                            "type": "abstract",
                            "text": "Consumer-level schema evidence.",
                        },
                        {
                            "id": "paper_keywords",
                            "type": "keywords",
                            "items": ["OpenXML", "OMML", "references"],
                        },
                        {
                            "id": "section_results",
                            "type": "heading",
                            "level": 1,
                            "text": "Results",
                        },
                        {
                            "id": "equation_energy",
                            "type": "equation",
                            "linear": "E = mc²",
                        },
                        {
                            "id": "equation_energy_caption",
                            "type": "equation_caption",
                            "target": "equation_energy",
                            "text": "Mass-energy equivalence",
                        },
                        {
                            "id": "reference_energy",
                            "type": "reference",
                            "target": "equation_energy",
                            "text": "Equation 1",
                        },
                        {
                            "id": "citation_notes",
                            "type": "citation",
                            "keys": ["lovelace1843"],
                        },
                        {
                            "id": "table_validation",
                            "type": "table",
                            "rows": [
                                ["Evidence", "Status"],
                                ["Open XML schema", "Pass"],
                            ],
                        },
                        {"id": "references", "type": "bibliography"},
                        {
                            "id": "reference_lovelace",
                            "type": "bibliography_entry",
                            "key": "lovelace1843",
                            "authors": ["Ada Lovelace"],
                            "year": 1843,
                            "title": "Notes",
                            "container": "Scientific Memoirs",
                        },
                    ],
                }
            },
        },
    )
    created = _public(project_root, "run", "--request", str(create_request))
    assert created["status"] == "success", created
    assert created["provider_chain"] == ["core-python"]

    read_request = _request(
        tmp_path,
        "real-academic-read.json",
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read = _public(project_root, "run", "--request", str(read_request))
    document = read["diagnostics"]["operation_result"]["document"]
    assert document["equations"] == [
        {
            "node_id": "equation_energy",
            "node_type": "equation",
            "linear": "E = mc²",
            "editable_omml": True,
        }
    ]
    assert document["references"]["status"] == "update_required"
    assert document["references"]["bindings"][0]["node_id"] == (
        "reference_energy"
    )

    schema = _run(
        project_root,
        tmp_path,
        "real-academic-schema.json",
        {
            "schema_version": "1.0",
            "operation": "docx.validate.schema",
            "input": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_errors": 100},
        },
    )
    schema_result = schema["diagnostics"]["operation_result"]["schema"]
    assert schema_result["valid"] is True
    schema_gate = next(
        gate
        for gate in schema["validation"]["gates"]
        if gate["id"] == "schema.full"
    )
    assert schema_gate["outcome"] == "pass"
    assert schema_gate["validator"] == "dotnet-openxml"
