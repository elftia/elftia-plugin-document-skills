"""Project supported Office Math into the canonical editable-equation AST.

Module provenance: original Elftia-authored clean-room implementation.
"""

from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import local_name
from .equation_ast import (
    UNICODE_TO_GREEK,
    ast_to_latex,
    canonicalize_math_text,
    normalize_ast,
)
from .equation_contracts import frame_to_bbox
from .equation_omml_tags import A, A14, M, MC, P


def is_equation_element(element: Element) -> bool:
    """Return whether *element* is one dedicated equation-block envelope."""
    if element.tag == P("sp"):
        return _is_dedicated_equation_shape(element)
    if element.tag != MC("AlternateContent"):
        return False
    choices = [child for child in element if child.tag == MC("Choice")]
    fallbacks = [child for child in element if child.tag == MC("Fallback")]
    if len(choices) != 1 or len(fallbacks) != 1:
        return False
    choice = choices[0]
    if "a14" not in choice.attrib.get("Requires", "").split():
        return False
    choice_shape = _only_shape(choice)
    fallback_shape = _only_shape(fallbacks[0])
    if choice_shape is None or fallback_shape is None:
        return False
    if not _is_dedicated_equation_shape(choice_shape):
        return False
    if not _is_generated_fallback_shape(fallback_shape):
        return False
    identity = _shape_identity(choice_shape)
    return identity is not None and identity == _shape_identity(fallback_shape)


def _is_dedicated_equation_shape(shape: Element) -> bool:
    if [child.tag for child in shape] != [P("nvSpPr"), P("spPr"), P("txBody")]:
        return False
    body = shape.find(P("txBody"))
    if body is None:
        return False
    if [child.tag for child in body] != [A("bodyPr"), A("lstStyle"), A("p")]:
        return False
    paragraphs = body.findall(A("p"))
    if len(paragraphs) != 1:
        return False
    paragraph = paragraphs[0]
    allowed = {A("endParaRPr"), A("pPr"), A14("m")}
    if any(child.tag not in allowed for child in paragraph):
        return False
    wrappers = [child for child in paragraph if child.tag == A14("m")]
    if len(wrappers) != 1:
        return False
    math_paragraphs = wrappers[0].findall(M("oMathPara"))
    return (
        len(math_paragraphs) == 1
        and len(math_paragraphs[0].findall(M("oMath"))) == 1
    )


def _is_generated_fallback_shape(shape: Element) -> bool:
    if [child.tag for child in shape] != [P("nvSpPr"), P("spPr"), P("txBody")]:
        return False
    body = shape.find(P("txBody"))
    if body is None or [child.tag for child in body] != [
        A("bodyPr"),
        A("lstStyle"),
        A("p"),
    ]:
        return False
    paragraph = body.find(A("p"))
    if paragraph is None or [child.tag for child in paragraph] != [A("r")]:
        return False
    run = paragraph.find(A("r"))
    return run is not None and [child.tag for child in run] == [A("rPr"), A("t")]


def _only_shape(parent: Element) -> Element | None:
    children = list(parent)
    if len(children) != 1 or children[0].tag != P("sp"):
        return None
    return children[0]


def _shape_identity(shape: Element) -> tuple[str, str] | None:
    properties = shape.find(f"{P('nvSpPr')}/{P('cNvPr')}")
    if properties is None:
        return None
    return properties.attrib.get("id", ""), properties.attrib.get("name", "")


def project_equation(element: Element, *, strict: bool = True) -> dict[str, Any]:
    properties = next(iter(element.iter(P("cNvPr"))), None)
    shape = _choice_shape(element)
    frame = _shape_frame(shape)
    math = next(iter(shape.iter(M("oMath"))), None)
    if properties is None or math is None:
        _validation("Editable equation is missing its identity or Office Math body.")
    try:
        ast = normalize_ast(_project_container(math))
    except DocumentSkillsError:
        if strict:
            raise
        return {
            "bbox": frame_to_bbox(frame),
            "editable": True,
            "format": "office-math",
            "id": properties.attrib.get("name", ""),
            "readback": {"status": "unsupported"},
        }
    return {
        "bbox": frame_to_bbox(frame),
        "canonical_ast": ast,
        "canonical_latex": ast_to_latex(ast),
        "consumer_compatibility": {
            "libreoffice": {"status": "not_run"},
            "powerpoint": {"status": "not_run"},
        },
        "editable": True,
        "fallback": "native",
        "format": "office-math",
        "id": properties.attrib.get("name", ""),
        "readback": {"status": "pass"},
    }


def _project_container(parent: Element) -> dict[str, Any]:
    items = [
        projected
        for child in list(parent)
        if (projected := _project_node(child)) is not None
    ]
    if not items:
        _validation("Office Math container is empty.")
    if len(items) == 1:
        return items[0]
    return {"type": "row", "items": items}


def _project_node(node: Element) -> dict[str, Any] | None:
    kind = local_name(node.tag)
    if kind in {
        "ctrlPr",
        "fPr",
        "mPr",
        "naryPr",
        "radPr",
        "sSubPr",
        "sSubSupPr",
        "sSupPr",
    }:
        return None
    if node.tag == M("r"):
        text = node.find(M("t"))
        value = "" if text is None else _normalize_math_text(text.text or "")
        if value in UNICODE_TO_GREEK:
            return {"type": "symbol", "name": UNICODE_TO_GREEK[value]}
        if not value:
            return None
        return {"type": "text", "value": value}
    if node.tag == M("f"):
        return {
            "type": "fraction",
            "numerator": _required_projection(
                node.find(M("num")), "fraction numerator"
            ),
            "denominator": _required_projection(
                node.find(M("den")), "fraction denominator"
            ),
        }
    if node.tag in {M("sSub"), M("sSup"), M("sSubSup")}:
        return _project_script(node)
    if node.tag == M("rad"):
        properties = node.find(M("radPr"))
        hidden = None if properties is None else properties.find(M("degHide"))
        degree = None
        if hidden is None or hidden.attrib.get(M("val")) not in {"1", "true"}:
            degree = _required_projection(node.find(M("deg")), "radical degree")
        return {
            "type": "radical",
            "radicand": _required_projection(node.find(M("e")), "radicand"),
            "degree": degree,
        }
    if node.tag == M("nary"):
        properties = node.find(M("naryPr"))
        operator = None if properties is None else properties.find(M("chr"))
        if operator is not None and operator.attrib.get(M("val"), "∑") != "∑":
            _validation(
                "Office Math n-ary operator is outside the supported sum subset."
            )
        return {
            "type": "nary",
            "operator": "sum",
            "lower": _optional_projection(node.find(M("sub"))),
            "upper": _optional_projection(node.find(M("sup"))),
        }
    if node.tag == M("m"):
        rows = []
        for row in node.findall(M("mr")):
            entries = [
                _required_projection(cell, "matrix cell")
                for cell in row.findall(M("e"))
            ]
            if not entries:
                _validation("Office Math matrix row is empty.")
            rows.append(entries)
        if not rows:
            _validation("Office Math matrix is empty.")
        return {"type": "matrix", "rows": rows}
    _validation("Office Math node is outside the supported readback subset.", node=kind)


def _project_script(node: Element) -> dict[str, Any]:
    result = {
        "type": {
            M("sSub"): "subscript",
            M("sSup"): "superscript",
            M("sSubSup"): "subsuperscript",
        }[node.tag],
        "base": _required_projection(node.find(M("e")), "script base"),
    }
    if node.tag in {M("sSub"), M("sSubSup")}:
        result["subscript"] = _required_projection(node.find(M("sub")), "subscript")
    if node.tag in {M("sSup"), M("sSubSup")}:
        result["exponent"] = _required_projection(node.find(M("sup")), "superscript")
    return result


def _required_projection(node: Element | None, field: str) -> dict[str, Any]:
    if node is None:
        _validation("Office Math required child is missing.", field=field)
    return _project_container(node)


def _optional_projection(node: Element | None) -> dict[str, Any] | None:
    if node is None:
        return None
    children = [child for child in node if local_name(child.tag) != "ctrlPr"]
    return None if not children else _project_container(node)


def _choice_shape(element: Element) -> Element:
    if element.tag == P("sp"):
        return element
    choice = element.find(MC("Choice"))
    shape = None if choice is None else choice.find(P("sp"))
    if shape is None:
        _validation("Editable equation AlternateContent choice is missing its shape.")
    return shape


def _shape_frame(shape: Element) -> dict[str, int]:
    transform = shape.find(f"{P('spPr')}/{A('xfrm')}")
    offset = None if transform is None else transform.find(A("off"))
    extent = None if transform is None else transform.find(A("ext"))
    if offset is None or extent is None:
        _validation("Editable equation frame is incomplete.")
    try:
        return {
            "x": int(offset.attrib["x"]),
            "y": int(offset.attrib["y"]),
            "cx": int(extent.attrib["cx"]),
            "cy": int(extent.attrib["cy"]),
        }
    except (KeyError, ValueError):
        _validation("Editable equation frame is invalid.")


def _normalize_math_text(value: str) -> str:
    return canonicalize_math_text(value)


def _validation(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        message,
        details=details,
    )


__all__ = ["is_equation_element", "project_equation"]
