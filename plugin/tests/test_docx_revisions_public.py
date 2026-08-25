"""Public revision filtering and scoped mutation regression tests."""

from pathlib import Path

import pytest

from document_skills_core.cli import execute_request
from document_skills_core.core.capabilities import (
    Capability,
    DetectionEvidence,
    Provider,
    ProviderCatalog,
    ProviderId,
)
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import sha256_file
from document_skills_core.formats.docx.service import DocxService


def test_public_revisions_apply_selects_filtered_nested_table_scope(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-revisions-nested.docx"
    source_sha256 = sha256_file(source)
    output = tmp_path / "nested-table-accepted.docx"
    filters = {"authors": ["Carol"], "types": ["insertion"]}
    public_scope = {
        "story": "body",
        "range": "table",
        "table_index": 1,
        "expected_table_sha256": (
            "05863db08075a5cbbc625625b0e0f5540b027e3c6ce23067b7cd6586c0518ae4"
        ),
    }
    provider_scope = {"story": "body", "range": "table", "table_index": 1}

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
                assert filters == {"authors": ["Carol"], "types": ["insertion"]}
                assert scope == provider_scope
                assert revision_ids is None
                return [
                    {
                        "id": "3",
                        "type": "insertion",
                        "author": "Carol",
                        "date": "2026-02-01T00:00:00Z",
                        "location": {
                            "story": "body",
                            "paragraph_index": 2,
                            "table_index": 1,
                        },
                    }
                ]
            assert limit == 1_001
            assert filters is None
            assert scope is None
            assert revision_ids == ["3"]
            return []

        def apply_revisions(
            self,
            input_path: Path,
            output_path: Path,
            revision_ids: list[str],
            action: str,
        ) -> dict[str, list[str]]:
            assert input_path == source
            assert revision_ids == ["3"]
            assert action == "accept"
            output_path.write_bytes(input_path.read_bytes())
            return {"matched_ids": ["3"], "unmatched_ids": []}

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
        "matched_ids": ["3"],
        "remaining_selected_ids": [],
        "unmatched_ids": [],
        "selection": {"filters": filters, "scope": public_scope},
    }
    assert output.is_file()
    assert sha256_file(source) == source_sha256
