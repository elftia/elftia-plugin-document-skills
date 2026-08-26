"""DOCX public-boundary tests split by operation family."""

from tests.support.docx_public import *  # noqa: F401,F403
from tests.support.docx_public import (
    _GIF,
    _PNG,
    _PNG_16,
    _public,
    _read_document,
    _report,
    _request,
    _table_values,
)

def test_public_revisions_read_uses_callable_dotnet_without_changing_source(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_root / "tests/fixtures/docx-revision-comments.docx"
    source_sha256 = sha256_file(source)

    class ControlledDotnet:
        def read_revisions(self, input_path: Path, limit: int) -> list[dict[str, str]]:
            assert input_path == source
            assert limit == 3
            return [
                {
                    "id": "1",
                    "type": "insertion",
                    "author": "Alice",
                    "date": "2026-01-01T00:00:00Z",
                    "location": {
                        "story": "body",
                        "paragraph_index": 12,
                        "table_index": None,
                    },
                },
                {
                    "id": "2",
                    "type": "deletion",
                    "author": "Bob",
                    "date": "2026-01-02T00:00:00Z",
                    "location": {
                        "story": "body",
                        "paragraph_index": 12,
                        "table_index": None,
                    },
                },
            ]

    service = DocxService(project_root, dotnet=ControlledDotnet())
    registry = ProviderCatalog()
    registry.register_provider(
        Provider(
            id=ProviderId.DOTNET_OPENXML,
            version="3.0.1",
            detect=lambda: DetectionEvidence(True, version="3.0.1"),
            execute=service.execute,
            capabilities=[Capability("docx.revisions.read", "enhanced")],
        )
    )
    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        lambda _project_root: registry,
    )
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.revisions.read",
            "input": str(source),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_revisions": 2},
        },
        project_root,
        SchemaCatalog(project_root),
    )

    assert result["status"] == "success"
    assert result["provider_chain"] == ["dotnet-openxml"]
    assert result["achieved_fidelity"] == "enhanced"
    assert result["diagnostics"]["operation_result"]["revisions"] == {
        "items": [
            {
                "id": "1",
                "type": "insertion",
                "author": "Alice",
                "date": "2026-01-01T00:00:00Z",
                "scope": {
                    "story": "body",
                    "paragraph_index": 12,
                    "expected_text": (
                        "revision-only {protected.revision}"
                        "deleted-only {protected.deleted}"
                        "field-only {protected.field}"
                    ),
                    "table_index": None,
                    "expected_table_sha256": None,
                },
            },
            {
                "id": "2",
                "type": "deletion",
                "author": "Bob",
                "date": "2026-01-02T00:00:00Z",
                "scope": {
                    "story": "body",
                    "paragraph_index": 12,
                    "expected_text": (
                        "revision-only {protected.revision}"
                        "deleted-only {protected.deleted}"
                        "field-only {protected.field}"
                    ),
                    "table_index": None,
                    "expected_table_sha256": None,
                },
            },
        ],
        "returned": 2,
        "truncated": False,
    }
    assert sha256_file(source) == source_sha256


def test_public_revisions_read_filters_and_projects_immutable_scope_metadata(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_root / "tests/fixtures/docx-revision-comments.docx"
    source_sha256 = sha256_file(source)
    expected_text = (
        "revision-only {protected.revision}"
        "deleted-only {protected.deleted}"
        "field-only {protected.field}"
    )
    filters = {
        "authors": ["Alice"],
        "types": ["insertion"],
        "date_from": "2026-01-01T00:00:00Z",
        "date_to": "2026-01-01T23:59:59Z",
    }
    scope = {
        "story": "body",
        "range": "paragraph",
        "paragraph_index": 12,
        "expected_text": expected_text,
    }

    class ControlledDotnet:
        def read_revisions(
            self,
            input_path: Path,
            limit: int,
            *,
            filters: dict[str, object] | None = None,
            scope: dict[str, object] | None = None,
            revision_ids: list[str] | None = None,
        ) -> list[dict[str, object]]:
            assert input_path == source
            assert limit == 2
            assert filters == {
                "authors": ["Alice"],
                "types": ["insertion"],
                "date_from": "2026-01-01T00:00:00Z",
                "date_to": "2026-01-01T23:59:59Z",
            }
            assert scope == {
                "story": "body",
                "range": "paragraph",
                "paragraph_index": 12,
            }
            assert revision_ids is None
            return [
                {
                    "id": "1",
                    "type": "insertion",
                    "author": "Alice",
                    "date": "2026-01-01T00:00:00Z",
                    "location": {
                        "story": "body",
                        "paragraph_index": 12,
                        "table_index": None,
                    },
                }
            ]

    service = DocxService(project_root, dotnet=ControlledDotnet())
    registry = ProviderCatalog()
    registry.register_provider(
        Provider(
            id=ProviderId.DOTNET_OPENXML,
            version="3.0.1",
            detect=lambda: DetectionEvidence(True, version="3.0.1"),
            execute=service.execute,
            capabilities=[Capability("docx.revisions.read", "enhanced")],
        )
    )
    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        lambda _project_root: registry,
    )
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.revisions.read",
            "input": str(source),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "max_revisions": 1,
                "filters": filters,
                "scope": scope,
            },
        },
        project_root,
        SchemaCatalog(project_root),
    )

    assert result["status"] == "success"
    assert result["diagnostics"]["operation_result"]["revisions"] == {
        "items": [
            {
                "id": "1",
                "type": "insertion",
                "author": "Alice",
                "date": "2026-01-01T00:00:00Z",
                "scope": {
                    "story": "body",
                    "paragraph_index": 12,
                    "expected_text": expected_text,
                    "table_index": None,
                    "expected_table_sha256": None,
                },
            }
        ],
        "returned": 1,
        "truncated": False,
    }
    assert sha256_file(source) == source_sha256


def test_public_revisions_read_filters_nested_scope_or_is_honestly_unavailable(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-revisions-nested.docx"
    source_sha256 = sha256_file(source)
    request = _request(
        tmp_path,
        "revisions-read.json",
        {
            "schema_version": "1.0",
            "operation": "docx.revisions.read",
            "input": str(source),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "max_revisions": 100,
                "filters": {"authors": ["Carol"], "types": ["insertion"]},
                "scope": {
                    "story": "body",
                    "range": "table",
                    "table_index": 1,
                    "expected_table_sha256": (
                        "05863db08075a5cbbc625625b0e0f5540"
                        "b027e3c6ce23067b7cd6586c0518ae4"
                    ),
                },
            },
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)

    assert sha256_file(source) == source_sha256
    if result["status"] == "success":
        assert result["provider_chain"] == ["dotnet-openxml"]
        assert result["validation"]["status"] == "pass"
        assert result["diagnostics"]["operation_result"]["revisions"]["items"] == [
            {
                "id": "3",
                "type": "insertion",
                "author": "Carol",
                "date": "2026-02-01T00:00:00Z",
                "scope": {
                    "story": "body",
                    "paragraph_index": 2,
                    "expected_text": "nested-table insertionnested-table deletion",
                    "table_index": 1,
                    "expected_table_sha256": (
                        "05863db08075a5cbbc625625b0e0f5540"
                        "b027e3c6ce23067b7cd6586c0518ae4"
                    ),
                },
            }
        ]
    else:
        assert result["status"] == "unavailable"
        assert result["provider_chain"] == []
        assert result["errors"][0]["code"] == "DS_PROVIDER_UNAVAILABLE"
