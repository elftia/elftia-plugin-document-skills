"""B6 contracts for bounded editable Office Math in PPTX."""

from pathlib import Path
from typing import Any

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pptx.contracts import parse_pptx_request
from document_skills_core.formats.pptx.equation_ast import normalize_equation_source
from document_skills_core.formats.pptx.equation_omml import (
    build_equation,
    project_equation,
)


def _equation(
    source: dict[str, Any],
    *,
    equation_id: str = "eq-growth",
) -> dict[str, Any]:
    return {
        "type": "equation",
        "id": equation_id,
        "bbox": {"x": 2.0, "y": 1.5, "w": 8.0, "h": 1.0},
        "source": source,
        "fallback": "reject",
    }


def _create_request(tmp_path: Path, equation: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "pptx.create",
        "output": str(tmp_path / "equation.pptx"),
        "arguments": {
            "deck": {
                "metadata": {
                    "title": "Editable equations",
                    "creator": "Elftia",
                    "subject": "B6",
                },
                "slides": [
                    {
                        "layout": "content",
                        "title": "Growth",
                        "shapes": [equation],
                        "table": None,
                        "chart_reference": None,
                        "image_reference": None,
                        "notes": None,
                    }
                ],
            }
        },
    }


def test_create_contract_normalizes_supported_latex(tmp_path: Path) -> None:
    parsed = parse_pptx_request(
        _create_request(
            tmp_path,
            _equation(
                {
                    "kind": "latex",
                    "value": r"\frac{E}{mc^2}+\sqrt{x}+\alpha",
                }
            ),
        )
    )

    equation = parsed.arguments["deck"]["slides"][0]["shapes"][0]
    assert equation["type"] == "equation"
    assert equation["id"] == "eq-growth"
    assert equation["bbox"] == {"x": 2.0, "y": 1.5, "w": 8.0, "h": 1.0}
    assert equation["canonical_latex"] == r"\frac{E}{mc^{2}}+\sqrt{x}+\alpha"
    assert equation["canonical_ast"]["type"] == "row"


def test_create_contract_accepts_typed_matrix_ast(tmp_path: Path) -> None:
    ast = {
        "type": "matrix",
        "rows": [
            [
                {"type": "text", "value": "a"},
                {"type": "symbol", "name": "beta"},
            ],
            [
                {
                    "type": "fraction",
                    "numerator": {"type": "text", "value": "1"},
                    "denominator": {"type": "text", "value": "2"},
                },
                {
                    "type": "radical",
                    "radicand": {"type": "text", "value": "x"},
                    "degree": None,
                },
            ],
        ],
    }
    parsed = parse_pptx_request(
        _create_request(tmp_path, _equation({"kind": "ast", "value": ast}))
    )

    equation = parsed.arguments["deck"]["slides"][0]["shapes"][0]
    assert equation["canonical_ast"] == ast
    assert equation["canonical_latex"] == (
        r"\begin{matrix}a & \beta \\ \frac{1}{2} & \sqrt{x}\end{matrix}"
    )


@pytest.mark.parametrize(
    ("value", "canonical"),
    [
        ("Ｆｕｌｌｗｉｄｔｈ+１", "Fullwidth+1"),
        ("x−1", "x-1"),
        ("中文[2]", "中文[2]"),
        ("x·y±1", "x·y±1"),
    ],
)
def test_typed_text_has_symmetric_latex_and_omml_canonicalization(
    tmp_path: Path,
    value: str,
    canonical: str,
) -> None:
    parsed = parse_pptx_request(
        _create_request(
            tmp_path,
            _equation(
                {
                    "kind": "ast",
                    "value": {"type": "text", "value": value},
                }
            ),
        )
    )
    equation = parsed.arguments["deck"]["slides"][0]["shapes"][0]

    latex_readback = normalize_equation_source(
        {"kind": "latex", "value": equation["canonical_latex"]},
        "roundtrip",
    )
    native_readback = project_equation(build_equation(7, equation))

    assert equation["canonical_ast"] == {"type": "text", "value": canonical}
    assert equation["canonical_latex"] == canonical
    assert latex_readback["canonical_ast"] == equation["canonical_ast"]
    assert native_readback["canonical_ast"] == equation["canonical_ast"]


@pytest.mark.parametrize("value", ["x_i", "α", "𝛂", "x y", "x\t+y"])
def test_typed_text_rejects_latex_reserved_greek_and_whitespace(
    tmp_path: Path,
    value: str,
) -> None:
    with pytest.raises(DocumentSkillsError) as captured:
        parse_pptx_request(
            _create_request(
                tmp_path,
                _equation(
                    {
                        "kind": "ast",
                        "value": {"type": "text", "value": value},
                    }
                ),
            )
        )

    assert captured.value.code == ErrorCode.UNSUPPORTED_FEATURE


@pytest.mark.parametrize(
    ("source", "code"),
    [
        (
            {"kind": "latex", "value": "<m:oMath><m:r/></m:oMath>"},
            ErrorCode.ARCHIVE_UNSAFE,
        ),
        ({"kind": "latex", "value": r"\input{secret.tex}"}, ErrorCode.ARCHIVE_UNSAFE),
        ({"kind": "latex", "value": r"\newcommand{\x}{1}"}, ErrorCode.ARCHIVE_UNSAFE),
        ({"kind": "latex", "value": r"\unknown{x}"}, ErrorCode.UNSUPPORTED_FEATURE),
        ({"kind": "omml", "value": "ignored"}, ErrorCode.ARCHIVE_UNSAFE),
    ],
)
def test_contract_rejects_raw_xml_macros_external_include_and_unknown_commands(
    tmp_path: Path,
    source: dict[str, Any],
    code: ErrorCode,
) -> None:
    with pytest.raises(DocumentSkillsError) as captured:
        parse_pptx_request(_create_request(tmp_path, _equation(source)))
    assert captured.value.code == code


def test_contract_reports_latex_length_and_ast_depth_as_resource_limits(
    tmp_path: Path,
) -> None:
    with pytest.raises(DocumentSkillsError) as long_latex:
        parse_pptx_request(
            _create_request(
                tmp_path,
                _equation({"kind": "latex", "value": "x" * 4_097}),
            )
        )
    assert long_latex.value.code == ErrorCode.RESOURCE_LIMIT

    node: dict[str, Any] = {"type": "text", "value": "x"}
    for _index in range(33):
        node = {"type": "radical", "radicand": node, "degree": None}
    with pytest.raises(DocumentSkillsError) as deep_ast:
        parse_pptx_request(
            _create_request(tmp_path, _equation({"kind": "ast", "value": node}))
        )
    assert deep_ast.value.code == ErrorCode.RESOURCE_LIMIT


@pytest.mark.parametrize(
    "bbox",
    [
        {"x": -0.1, "y": 1.0, "w": 1.0, "h": 1.0},
        {"x": 1.0, "y": 1.0, "w": 0.0, "h": 1.0},
        {"x": 9.5, "y": 1.0, "w": 1.0, "h": 1.0},
        {"x": 1.0, "y": 7.0, "w": 1.0, "h": 1.0},
        {"x": 1.0, "y": 1.0, "w": 1e-12, "h": 1.0},
        {"x": float("inf"), "y": 1.0, "w": 1.0, "h": 1.0},
    ],
)
def test_equation_bbox_rejects_invalid_or_out_of_slide_geometry(
    tmp_path: Path,
    bbox: dict[str, float],
) -> None:
    equation = _equation({"kind": "latex", "value": "x"})
    equation["bbox"] = bbox

    with pytest.raises(DocumentSkillsError) as captured:
        parse_pptx_request(_create_request(tmp_path, equation))

    assert captured.value.code == ErrorCode.REQUEST_INVALID


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        (
            [[{"type": "text", "value": "x"}]] * 9,
            ErrorCode.RESOURCE_LIMIT,
        ),
        (
            [[{"type": "text", "value": "x"}] * 9],
            ErrorCode.RESOURCE_LIMIT,
        ),
        (
            [
                [{"type": "text", "value": "x"}],
                [
                    {"type": "text", "value": "x"},
                    {"type": "text", "value": "y"},
                ],
            ],
            ErrorCode.REQUEST_INVALID,
        ),
    ],
)
def test_typed_matrix_rejects_row_column_and_rectangularity_violations(
    tmp_path: Path,
    rows: list[list[dict[str, Any]]],
    code: ErrorCode,
) -> None:
    with pytest.raises(DocumentSkillsError) as captured:
        parse_pptx_request(
            _create_request(
                tmp_path,
                _equation({"kind": "ast", "value": {"type": "matrix", "rows": rows}}),
            )
        )

    assert captured.value.code == code


def test_typed_matrix_accepts_exact_eight_by_eight_boundary(tmp_path: Path) -> None:
    rows = [
        [{"type": "text", "value": f"{row}{column}"} for column in range(8)]
        for row in range(8)
    ]

    parsed = parse_pptx_request(
        _create_request(
            tmp_path,
            _equation({"kind": "ast", "value": {"type": "matrix", "rows": rows}}),
        )
    )

    equation = parsed.arguments["deck"]["slides"][0]["shapes"][0]
    assert equation["canonical_ast"] == {"type": "matrix", "rows": rows}


def test_latex_matrix_obeys_one_global_ast_node_budget(tmp_path: Path) -> None:
    cell = r"\frac{\frac{x}{y}}{\frac{x}{y}}"
    row = " & ".join([cell] * 8)
    latex = r"\begin{matrix}" + r" \\ ".join([row] * 8) + r"\end{matrix}"

    with pytest.raises(DocumentSkillsError) as captured:
        parse_pptx_request(
            _create_request(
                tmp_path,
                _equation({"kind": "latex", "value": latex}),
            )
        )

    assert captured.value.code == ErrorCode.RESOURCE_LIMIT


@pytest.mark.parametrize(
    "ast",
    [
        {"type": "text", "value": "x", "unexpected": True},
        {
            "type": "fraction",
            "numerator": {"type": "text", "value": "x", "unexpected": True},
            "denominator": {"type": "text", "value": "y"},
        },
    ],
)
def test_typed_ast_rejects_unknown_fields_at_every_depth(
    tmp_path: Path,
    ast: dict[str, Any],
) -> None:
    with pytest.raises(DocumentSkillsError) as captured:
        parse_pptx_request(
            _create_request(
                tmp_path,
                _equation({"kind": "ast", "value": ast}),
            )
        )

    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_edit_contract_accepts_equation_add_and_selected_update(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pptx"
    source.write_bytes(b"not opened while parsing")
    request = {
        "schema_version": "1.0",
        "operation": "pptx.edit",
        "input": str(source),
        "output": str(tmp_path / "updated.pptx"),
        "arguments": {
            "edits": [
                {
                    "type": "equation_upsert",
                    "slide": 1,
                    "equation": _equation({"kind": "latex", "value": "E=mc^2"}),
                },
                {
                    "type": "equation_upsert",
                    "slide": 1,
                    "selector": {"id": "7", "name": "eq-growth", "type": "equation"},
                    "precondition_sha256": "0" * 64,
                    "equation": _equation(
                        {"kind": "latex", "value": r"\sum_{i=1}^{n}i"}
                    ),
                },
            ]
        },
    }

    parsed = parse_pptx_request(request)

    add, update = parsed.arguments["edits"]
    assert add["selector"] is None
    assert add["equation"]["canonical_latex"] == "E=mc^{2}"
    assert update["selector"]["type"] == "equation"
    assert update["equation"]["canonical_latex"] == r"\sum_{i=1}^{n}i"
