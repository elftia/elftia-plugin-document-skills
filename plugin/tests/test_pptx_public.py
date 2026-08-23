"""PPTX public command surface tests — frozen uv subprocess boundary."""

import json
from pathlib import Path
import subprocess

import pytest

from document_skills_core.core.contracts.schemas import SchemaCatalog
from tests.fixtures.recipes.docx_fixture_support import PNG_1X1


def _public(
    project_root: Path,
    *arguments: str,
    check: bool = True,
    cwd: Path | None = None,
) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-pptx/scripts/run.py"),
            *arguments,
        ],
        cwd=cwd or project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=60,
    )
    if check:
        assert process.returncode == 0, (
            process.stderr.decode("utf-8", errors="replace")
            or process.stdout.decode("utf-8", errors="replace")
        )
    assert process.stderr == b""
    text = process.stdout.decode("utf-8", errors="strict")
    decoder = json.JSONDecoder()
    payload, end = decoder.raw_decode(text)
    assert text[end:].strip() == ""
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


def _deck(image_path: Path) -> dict[str, object]:
    return {
        "metadata": {"title": "Public PPTX", "creator": "Test", "subject": ""},
        "slide_size": {"cx": "9144000", "cy": "6858000", "type": "screen4x3"},
        "slides": [
            {
                "layout": "title",
                "title": "Title",
                "shapes": [
                    {"text": "Body", "runs": [{"text": "Body", "style": None}]}
                ],
                "table": None,
                "chart_reference": None,
                "image_reference": None,
                "notes": "Speaker notes",
            },
            {
                "layout": "content",
                "title": "Content",
                "shapes": [
                    {"text": "Content body", "runs": [{"text": "Content", "style": None}]}
                ],
                "table": {"rows": [{"cells": ["A", "B"]}]},
                "chart_reference": {
                    "title": "Chart",
                    "chart_type": "column",
                    "categories": ["North", "South"],
                    "series": [{"name": "Sales", "values": [4, 7]}],
                    "legend": {"show": True, "position": "bottom"},
                    "axes": {
                        "category": {"title": "Region", "number_format": "General"},
                        "value": {"title": "Units", "number_format": "0"},
                    },
                    "data_labels": {"show_value": True},
                    "colors": ["3366CC"],
                },
                "image_reference": {
                    "path": str(image_path),
                    "content_type": "image/png",
                    "fit": "contain",
                    "alt_text": "Public embedded image",
                },
                "notes": None,
            },
        ],
    }


@pytest.fixture
def public_created(project_root: Path, tmp_path: Path) -> Path:
    from pptx import Presentation

    output = tmp_path / "public-created.pptx"
    presentation = Presentation()
    first = presentation.slides.add_slide(presentation.slide_layouts[1])
    first.shapes.title.text = "Title"
    first.placeholders[1].text = "Body"
    second = presentation.slides.add_slide(presentation.slide_layouts[1])
    second.shapes.title.text = "Content"
    second.placeholders[1].text = "Content body"
    presentation.save(output)
    return output


def test_public_capabilities_list_pptx_operations(project_root: Path) -> None:
    report = _public(project_root, "capabilities", "--json")
    operations = {item["operation"]: item for item in report["operations"]}
    core = ("pptx.read", "pptx.inspect.structure", "pptx.create", "pptx.edit")
    for operation in core:
        assert operation in operations
        assert operations[operation]["available"], operations[operation]

    # Provider-backed operations are environment-dependent by design:
    # `pptx.create.from-html` is served solely by `html-browser`, which is
    # optional (`required=False`) and needs Node, the locked Playwright library
    # and a launchable Chromium-family browser. It is genuinely unavailable
    # without one. `tests/test_runtime.py` asserts that sole-provider binding.
    #
    # The blanket "every pptx operation is available" assertion this replaces
    # asserted the opposite of what capability discovery exists for. Scope of
    # that failure, from run 31529508680: the two ubuntu legs failed here
    # (1 failed, 1026 passed, 26 skipped); the windows legs failed a different
    # test and the macos legs failed 86. This repair addresses the ubuntu
    # failure only.
    #
    # The check below is a regression guard over `reports.py`, not an exercised
    # negative path: that module sets a constant non-empty reason whenever
    # `available` is false, so today's production output cannot reach the
    # failure branch. It exists so a later change cannot publish a missing
    # provider as a silent, reasonless absence.
    for operation, item in operations.items():
        if "pptx" not in operation or operation in core:
            continue
        assert item["available"] or item["reason"], item


def test_public_doctor_succeeds(project_root: Path) -> None:
    report = _public(project_root, "doctor", "--json")
    assert report["status"] == "healthy"


def test_public_create_and_read(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    read_request = _request(
        tmp_path,
        "read.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.read",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(read_request))
    assert result["status"] == "success"
    assert result["diagnostics"]["operation_result"]["slide_count"] == 2


def test_public_inspect_inert(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    inspect_request = _request(
        tmp_path,
        "inspect.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.inspect.structure",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(inspect_request))
    assert result["status"] == "success"
    assert result["diagnostics"]["operation_result"]["mutation_authorized"] is False


def test_public_edit_produces_distinct_output(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-edited.pptx"
    edit_request = _request(
        tmp_path,
        "edit.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"slide": 1, "type": "slide_text", "ref": "", "value": "Modified"},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request))
    assert result["status"] == "success"
    assert output.is_file()
    assert public_created.is_file()
    assert any(item["path"] == str(output.resolve()) for item in result["artifacts"])


def test_public_reorder_preserves_slides(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-reordered.pptx"
    edit_request = _request(
        tmp_path,
        "reorder.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"slide": 2, "type": "slide_reorder", "ref": "", "value": "1"},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request))
    assert result["status"] == "success"
    op_result = result["diagnostics"]["operation_result"]
    assert "reorder" in op_result
    assert op_result["reorder"][0]["shape_ids_preserved"] is True


def test_public_validate_reopens_valid_pptx(project_root: Path, public_created: Path) -> None:
    result = _public(
        project_root,
        "validate",
        "--input",
        str(public_created),
        "--json",
    )
    outcomes = {item["id"]: item["outcome"] for item in result["gates"]}
    assert result["status"] == "pass"
    assert outcomes["provider.reopen"] == "pass"
    assert outcomes["visual.render"] == "unavailable"
    assert outcomes["schema.full"] == "unavailable"


def test_public_unknown_operation_rejected(project_root: Path, tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        "unknown.json",
        {
            "schema_version": "1.0",
            "operation": "pptx.nonexistent",
            "input": str(tmp_path / "input.pptx"),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)
    assert result["status"] == "invalid_request"


def test_public_create_is_deterministic(project_root: Path, tmp_path: Path) -> None:
    output1 = tmp_path / "d1.pptx"
    output2 = tmp_path / "d2.pptx"
    image = tmp_path / "img.png"
    image.write_bytes(PNG_1X1)
    results = []
    for out in [output1, output2]:
        req = _request(tmp_path, f"create_{out.stem}.json", {
            "schema_version": "1.0",
            "operation": "pptx.create",
            "output": str(out),
            "arguments": {"deck": _deck(image)},
        })
        results.append(
            _public(project_root, "run", "--request", str(req), check=False)
        )
    assert all(result["status"] == "success" for result in results)
    assert all(result["artifacts"] for result in results)
    assert output1.exists() and output2.exists()
    candidate_hashes = [
        next(
            gate["evidence"]["sha256"]
            for gate in result["validation"]["gates"]
            if gate["id"] == "artifact.exists-size"
        )
        for result in results
    ]
    assert candidate_hashes[0] == candidate_hashes[1]


def test_public_create_reopens_real_native_objects(project_root: Path, tmp_path: Path) -> None:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    image = tmp_path / "native.png"
    image.write_bytes(PNG_1X1)
    output = tmp_path / "native-objects.pptx"
    request = _request(tmp_path, "native-create.json", {
        "schema_version": "1.0",
        "operation": "pptx.create",
        "output": str(output),
        "arguments": {"deck": _deck(image)},
    })
    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success"
    creation = result["diagnostics"]["operation_result"]["creation"]
    assert creation["images"][0]["embedded_media_part"] == "ppt/media/image1.png"
    assert creation["images"][0]["fallback"] == "native"
    assert creation["charts"][0]["editable"] is True
    outcomes = {gate["id"]: gate["outcome"] for gate in result["validation"]["gates"]}
    assert outcomes["visual.render"] == "unavailable"
    presentation = Presentation(output)
    assert len(presentation.slides) == 2
    shapes = list(presentation.slides[1].shapes)
    assert any(shape.shape_type == MSO_SHAPE_TYPE.PICTURE for shape in shapes)
    chart_shapes = [shape for shape in shapes if getattr(shape, "has_chart", False)]
    assert len(chart_shapes) == 1
    assert list(chart_shapes[0].chart.series[0].values) == [4.0, 7.0]
    assert any(getattr(shape, "has_table", False) for shape in shapes)


def test_public_create_missing_image_fails_closed(project_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "must-not-exist.pptx"
    request = _request(tmp_path, "missing-image.json", {
        "schema_version": "1.0",
        "operation": "pptx.create",
        "output": str(output),
        "arguments": {"deck": _deck(tmp_path / "missing.png")},
    })
    result = _public(project_root, "run", "--request", str(request), check=False)
    assert result["status"] == "invalid_request"
    assert not output.exists()
