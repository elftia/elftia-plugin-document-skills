import copy
import json

import pytest

from document_skills_core.cli import execute_request
from document_skills_core.core.contracts import DocumentSkillsError, ErrorCode, SchemaCatalog
from document_skills_core.core.contracts.serialization import load_json_file

_REQUEST_FILE_BYTES = 1_048_576


def test_all_schema_examples_and_fingerprints_are_stable(project_root):
    catalog = SchemaCatalog(project_root)
    catalog.validate_examples()
    first = catalog.fingerprints()
    second = SchemaCatalog(project_root).fingerprints()
    assert first == second
    assert set(first) == {
        "capability-report",
        "doctor-report",
        "docx-template-pack",
        "operation-request",
        "operation-result",
        "validation-report",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda request: request.update(schema_version="2.0"),
        lambda request: request.pop("operation"),
        lambda request: request.update(extra=True),
        lambda request: request.update(options={"allow_degraded": "yes"}),
    ],
)
def test_invalid_requests_fail_before_dispatch(project_root, mutation):
    catalog = SchemaCatalog(project_root)
    request = {"schema_version": "1.0", "operation": "docx.read"}
    mutation(request)
    result = execute_request(request, project_root, catalog)
    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == ErrorCode.REQUEST_INVALID


def test_unknown_operation_has_stable_mapping(project_root):
    catalog = SchemaCatalog(project_root)
    result = execute_request(
        {"schema_version": "1.0", "operation": "docx.not-registered"},
        project_root,
        catalog,
    )
    catalog.validate("operation-result", result)
    assert result["operation"] == "docx.not-registered"
    assert result["errors"][0]["code"] == ErrorCode.OPERATION_UNKNOWN


def test_invalid_result_json_is_rejected(project_root):
    catalog = SchemaCatalog(project_root)
    example = copy.deepcopy(
        json.loads((project_root / "schemas" / "operation-result.schema.json").read_text())[
            "examples"
        ][0]
    )
    example["status"] = "pretend-success"
    with pytest.raises(DocumentSkillsError) as caught:
        catalog.validate("operation-result", example)
    assert caught.value.code == ErrorCode.REQUEST_INVALID


def test_request_file_loader_accepts_boundary_and_rejects_boundary_plus_one(
    tmp_path,
):
    boundary = tmp_path / "boundary.json"
    boundary.write_bytes(b"{}" + b" " * (_REQUEST_FILE_BYTES - 2))
    assert load_json_file(str(boundary)) == {}

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(boundary.read_bytes() + b" ")
    with pytest.raises(ValueError, match="byte limit"):
        load_json_file(str(oversized))
