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

def test_public_comments_read_returns_bounded_anchored_projection(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_root / "tests/fixtures/docx-revision-comments.docx"
    source_sha256 = sha256_file(source)

    class ControlledDotnet:
        def read_comments(self, input_path: Path, limit: int) -> list[dict[str, object]]:
            assert input_path == source
            assert limit == 2
            return [
                {
                    "id": "0",
                    "parent_comment_id": None,
                    "thread_id": "0",
                    "resolved": False,
                    "author": "Reviewer",
                    "date": "2026-08-24T00:00:00Z",
                    "text": "Please clarify this paragraph.",
                    "anchor": {
                        "story": "body",
                        "paragraph_index": 1,
                        "range": "paragraph",
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
            capabilities=[Capability("docx.comments.read", "enhanced")],
        )
    )
    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        lambda _project_root: registry,
    )
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.comments.read",
            "input": str(source),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_comments": 1},
        },
        project_root,
        SchemaCatalog(project_root),
    )

    assert result["status"] == "success"
    assert result["provider_chain"] == ["dotnet-openxml"]
    assert result["diagnostics"]["operation_result"]["comments"] == {
        "items": [
            {
                "id": "0",
                "parent_comment_id": None,
                "thread_id": "0",
                "resolved": False,
                "author": "Reviewer",
                "date": "2026-08-24T00:00:00Z",
                "text": "Please clarify this paragraph.",
                "anchor": {
                    "story": "body",
                    "paragraph_index": 1,
                    "range": "paragraph",
                },
            }
        ],
        "returned": 1,
        "truncated": False,
    }
    assert sha256_file(source) == source_sha256


def test_public_comments_add_validates_anchor_and_promotes_candidate(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-revision-comments.docx"
    source_sha256 = sha256_file(source)
    output = tmp_path / "commented.docx"
    anchor = {
        "story": "body",
        "paragraph_index": 0,
        "expected_text": "Core DOCX",
        "range": "paragraph",
    }

    class ControlledDotnet:
        def add_comment(
            self,
            input_path: Path,
            output_path: Path,
            comment: dict[str, object],
        ) -> str:
            assert input_path == source
            assert comment == {
                "author": "Reviewer",
                "text": "Please clarify this heading.",
                "anchor": anchor,
                "parent_comment_id": None,
            }
            output_path.write_bytes(input_path.read_bytes())
            return "1"

        def read_comments(self, input_path: Path, limit: int) -> list[dict[str, object]]:
            assert input_path != source
            assert limit == 10_001
            return [
                {
                    "id": "1",
                    "parent_comment_id": None,
                    "thread_id": "1",
                    "resolved": False,
                    "author": "Reviewer",
                    "date": "2026-08-24T00:00:00Z",
                    "text": "Please clarify this heading.",
                    "anchor": {
                        "story": "body",
                        "paragraph_index": 0,
                        "range": "paragraph",
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
            capabilities=[Capability("docx.comments.add", "enhanced")],
        )
    )
    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        lambda _project_root: registry,
    )
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.comments.add",
            "input": str(source),
            "output": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "author": "Reviewer",
                "text": "Please clarify this heading.",
                "anchor": anchor,
            },
        },
        project_root,
        SchemaCatalog(project_root),
    )

    assert result["status"] == "success"
    assert result["provider_chain"] == ["dotnet-openxml"]
    assert result["diagnostics"]["operation_result"]["comment"] == {
        "id": "1",
        "parent_comment_id": None,
        "thread_id": "1",
        "resolved": False,
        "author": "Reviewer",
        "date": "2026-08-24T00:00:00Z",
        "text": "Please clarify this heading.",
        "anchor": {
            "story": "body",
            "paragraph_index": 0,
            "range": "paragraph",
        },
    }
    assert output.is_file()
    assert sha256_file(source) == source_sha256


def test_public_comments_resolve_failure_preserves_existing_destination(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-revision-comments.docx"
    source_sha256 = sha256_file(source)
    output = tmp_path / "resolved.docx"
    original_destination = b"existing destination"
    output.write_bytes(original_destination)

    class FailingDotnet:
        def resolve_comment(
            self,
            input_path: Path,
            output_path: Path,
            comment_id: str,
            resolved: bool,
        ) -> dict[str, object]:
            output_path.write_bytes(input_path.read_bytes())
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "controlled comment resolution failure",
            )

    service = DocxService(project_root, dotnet=FailingDotnet())
    registry = ProviderCatalog()
    registry.register_provider(
        Provider(
            id=ProviderId.DOTNET_OPENXML,
            version="3.0.1",
            detect=lambda: DetectionEvidence(True, version="3.0.1"),
            execute=service.execute,
            capabilities=[Capability("docx.comments.resolve", "enhanced")],
        )
    )
    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        lambda _project_root: registry,
    )
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.comments.resolve",
            "input": str(source),
            "output": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {"comment_id": "0", "resolved": True},
        },
        project_root,
        SchemaCatalog(project_root),
    )

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_PROVIDER_FAILED"
    assert output.read_bytes() == original_destination
    assert sha256_file(source) == source_sha256


def test_public_schema_validation_marks_gate_pass_only_after_validator_runs(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_root / "tests/fixtures/docx-rich.docx"
    source_sha256 = sha256_file(source)

    class ControlledDotnet:
        def validate_schema(self, input_path: Path, limit: int) -> dict[str, object]:
            assert input_path == source
            assert limit == 51
            return {"valid": True, "errors": []}

    service = DocxService(project_root, dotnet=ControlledDotnet())
    registry = ProviderCatalog()
    registry.register_provider(
        Provider(
            id=ProviderId.DOTNET_OPENXML,
            version="3.0.1",
            detect=lambda: DetectionEvidence(True, version="3.0.1"),
            execute=service.execute,
            capabilities=[Capability("docx.validate.schema", "enhanced")],
            validators={"schema": ControlledDotnet().validate_schema},
        )
    )
    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        lambda _project_root: registry,
    )
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.validate.schema",
            "input": str(source),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_errors": 50},
        },
        project_root,
        SchemaCatalog(project_root),
    )

    assert result["status"] == "success"
    assert result["provider_chain"] == ["dotnet-openxml"]
    assert result["diagnostics"]["operation_result"]["schema"] == {
        "valid": True,
        "errors": [],
        "returned_errors": 0,
        "truncated": False,
    }
    schema_gate = next(
        gate for gate in result["validation"]["gates"] if gate["id"] == "schema.full"
    )
    assert schema_gate["outcome"] == "pass"
    assert schema_gate["validator"] == "dotnet-openxml"
    assert sha256_file(source) == source_sha256
