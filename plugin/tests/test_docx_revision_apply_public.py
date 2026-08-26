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

def test_public_revisions_apply_validates_and_promotes_distinct_output(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-revision-comments.docx"
    source_sha256 = sha256_file(source)
    output = tmp_path / "accepted.docx"

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
            assert limit >= 2
            if input_path == source:
                assert filters is None
                assert scope is None
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
            assert revision_ids == ["1"]
            return []

        def apply_revisions(
            self,
            input_path: Path,
            output_path: Path,
            revision_ids: list[str],
            action: str,
        ) -> dict[str, list[str]]:
            assert input_path == source
            assert revision_ids == ["1"]
            assert action == "accept"
            output_path.write_bytes(input_path.read_bytes())
            return {"matched_ids": ["1"], "unmatched_ids": []}

    service = DocxService(project_root, dotnet=ControlledDotnet())
    registry = ProviderCatalog()
    registry.register_provider(
        Provider(
            id=ProviderId.DOTNET_OPENXML,
            version="3.0.1",
            detect=lambda: DetectionEvidence(True, version="3.0.1"),
            execute=service.execute,
            capabilities=[Capability("docx.revisions.apply", "enhanced")],
        )
    )
    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        lambda _project_root: registry,
    )
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.revisions.apply",
            "input": str(source),
            "output": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {"action": "accept", "revision_ids": ["1"]},
        },
        project_root,
        SchemaCatalog(project_root),
    )

    assert result["status"] == "success"
    assert result["provider_chain"] == ["dotnet-openxml"]
    assert result["achieved_fidelity"] == "enhanced"
    assert result["diagnostics"]["operation_result"]["revisions"] == {
        "action": "accept",
        "matched_ids": ["1"],
        "remaining_selected_ids": [],
        "unmatched_ids": [],
    }
    assert output.is_file()
    assert sha256_file(source) == source_sha256
    SchemaCatalog(project_root).validate("operation-result", result)


def test_public_revisions_apply_selects_filtered_paragraph_scope(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-revision-comments.docx"
    source_sha256 = sha256_file(source)
    output = tmp_path / "alice-paragraph-accepted.docx"
    expected_text = (
        "revision-only {protected.revision}"
        "deleted-only {protected.deleted}"
        "field-only {protected.field}"
    )
    filters = {"authors": ["Alice"], "types": ["insertion"]}
    public_scope = {
        "story": "body",
        "range": "paragraph",
        "paragraph_index": 12,
        "expected_text": expected_text,
    }
    provider_scope = {
        "story": "body",
        "range": "paragraph",
        "paragraph_index": 12,
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
            if input_path == source:
                assert limit == 1_001
                assert filters == {"authors": ["Alice"], "types": ["insertion"]}
                assert scope == provider_scope
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
            assert limit == 1_001
            assert filters is None
            assert scope is None
            assert revision_ids == ["1"]
            return []

        def apply_revisions(
            self,
            input_path: Path,
            output_path: Path,
            revision_ids: list[str],
            action: str,
        ) -> dict[str, list[str]]:
            assert input_path == source
            assert revision_ids == ["1"]
            assert action == "accept"
            output_path.write_bytes(input_path.read_bytes())
            return {"matched_ids": ["1"], "unmatched_ids": []}

    service = DocxService(project_root, dotnet=ControlledDotnet())
    registry = ProviderCatalog()
    registry.register_provider(
        Provider(
            id=ProviderId.DOTNET_OPENXML,
            version="3.0.1",
            detect=lambda: DetectionEvidence(True, version="3.0.1"),
            execute=service.execute,
            capabilities=[Capability("docx.revisions.apply", "enhanced")],
        )
    )
    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        lambda _project_root: registry,
    )
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.revisions.apply",
            "input": str(source),
            "output": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "action": "accept",
                "filters": filters,
                "scope": public_scope,
            },
        },
        project_root,
        SchemaCatalog(project_root),
    )

    assert result["status"] == "success", result
    assert result["diagnostics"]["operation_result"]["revisions"] == {
        "action": "accept",
        "matched_ids": ["1"],
        "remaining_selected_ids": [],
        "unmatched_ids": [],
        "selection": {"filters": filters, "scope": public_scope},
    }
    assert output.is_file()
    assert sha256_file(source) == source_sha256


def test_public_revisions_apply_preserves_destination_when_target_is_missing(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-revision-comments.docx"
    source_sha256 = sha256_file(source)
    output = tmp_path / "existing.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)

    class MissingRevisionDotnet:
        def apply_revisions(
            self,
            input_path: Path,
            output_path: Path,
            revision_ids: list[str],
            action: str,
        ) -> dict[str, list[str]]:
            output_path.write_bytes(input_path.read_bytes())
            return {"matched_ids": [], "unmatched_ids": revision_ids}

    service = DocxService(project_root, dotnet=MissingRevisionDotnet())
    registry = ProviderCatalog()
    registry.register_provider(
        Provider(
            id=ProviderId.DOTNET_OPENXML,
            version="3.0.1",
            detect=lambda: DetectionEvidence(True, version="3.0.1"),
            execute=service.execute,
            capabilities=[Capability("docx.revisions.apply", "enhanced")],
        )
    )
    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        lambda _project_root: registry,
    )
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.revisions.apply",
            "input": str(source),
            "output": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {"action": "reject", "revision_ids": ["missing"]},
        },
        project_root,
        SchemaCatalog(project_root),
    )

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert output.read_bytes() == original_destination
    assert sha256_file(source) == source_sha256
