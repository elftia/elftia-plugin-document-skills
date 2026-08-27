"""Emit the accepted typed math AST as native editable Office Math.

Module provenance: original Elftia-authored clean-room implementation.
"""

from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element, SubElement

from .equation_ast import GREEK_SYMBOLS
from .equation_omml_tags import A, A14, M, MC, P, XML_SPACE


def build_equation(shape_id: int, equation: dict[str, Any]) -> Element:
    alternate = Element(MC("AlternateContent"))
    choice = SubElement(alternate, MC("Choice"), {"Requires": "a14"})
    choice.append(_equation_shape(shape_id, equation))
    fallback = SubElement(alternate, MC("Fallback"))
    fallback.append(_fallback_shape(shape_id, equation))
    return alternate


def _equation_shape(shape_id: int, equation: dict[str, Any]) -> Element:
    shape = Element(P("sp"))
    _append_non_visual(shape, shape_id, equation["id"], fallback=False)
    _append_shape_properties(shape, equation["frame"])
    body = SubElement(shape, P("txBody"))
    body_properties = SubElement(body, A("bodyPr"), {"wrap": "square"})
    SubElement(body_properties, A("spAutoFit"))
    SubElement(body, A("lstStyle"))
    paragraph = SubElement(body, A("p"))
    SubElement(paragraph, A("pPr"))
    math_wrapper = SubElement(paragraph, A14("m"))
    math_paragraph = SubElement(math_wrapper, M("oMathPara"))
    math = SubElement(math_paragraph, M("oMath"))
    _emit_node(math, equation["canonical_ast"])
    SubElement(paragraph, A("endParaRPr"), {"lang": "en-US"})
    return shape


def _fallback_shape(shape_id: int, equation: dict[str, Any]) -> Element:
    shape = Element(P("sp"))
    _append_non_visual(shape, shape_id, equation["id"], fallback=True)
    _append_shape_properties(shape, equation["frame"])
    body = SubElement(shape, P("txBody"))
    body_properties = SubElement(body, A("bodyPr"), {"wrap": "square"})
    SubElement(body_properties, A("spAutoFit"))
    SubElement(body, A("lstStyle"))
    paragraph = SubElement(body, A("p"))
    run = SubElement(paragraph, A("r"))
    _drawing_run_properties(run)
    text = SubElement(run, A("t"))
    text.text = equation["canonical_latex"]
    return shape


def _append_non_visual(
    shape: Element,
    shape_id: int,
    name: str,
    *,
    fallback: bool,
) -> None:
    non_visual = SubElement(shape, P("nvSpPr"))
    SubElement(non_visual, P("cNvPr"), {"id": str(shape_id), "name": name})
    locks = SubElement(non_visual, P("cNvSpPr"), {"txBox": "1"})
    if fallback:
        SubElement(
            locks,
            A("spLocks"),
            {
                "noAdjustHandles": "1",
                "noChangeArrowheads": "1",
                "noChangeAspect": "1",
                "noChangeShapeType": "1",
                "noEditPoints": "1",
                "noMove": "1",
                "noResize": "1",
                "noRot": "1",
                "noTextEdit": "1",
            },
        )
    SubElement(non_visual, P("nvPr"))


def _append_shape_properties(shape: Element, frame: dict[str, int]) -> None:
    properties = SubElement(shape, P("spPr"))
    transform = SubElement(properties, A("xfrm"))
    SubElement(transform, A("off"), {"x": str(frame["x"]), "y": str(frame["y"])})
    SubElement(
        transform,
        A("ext"),
        {"cx": str(frame["cx"]), "cy": str(frame["cy"])},
    )
    geometry = SubElement(properties, A("prstGeom"), {"prst": "rect"})
    SubElement(geometry, A("avLst"))
    SubElement(properties, A("noFill"))


def _emit_node(parent: Element, node: dict[str, Any]) -> None:
    kind = node["type"]
    if kind == "row":
        for item in node["items"]:
            _emit_node(parent, item)
        return
    if kind in {"symbol", "text"}:
        value = node["value"] if kind == "text" else GREEK_SYMBOLS[node["name"]]
        _math_run(parent, value)
        return
    if kind == "fraction":
        fraction = SubElement(parent, M("f"))
        _control_properties(SubElement(fraction, M("fPr")))
        numerator = SubElement(fraction, M("num"))
        denominator = SubElement(fraction, M("den"))
        _emit_node(numerator, node["numerator"])
        _emit_node(denominator, node["denominator"])
        return
    if kind in {"subscript", "superscript", "subsuperscript"}:
        _emit_script(parent, node)
        return
    if kind == "radical":
        radical = SubElement(parent, M("rad"))
        properties = SubElement(radical, M("radPr"))
        if node["degree"] is None:
            SubElement(properties, M("degHide"), {M("val"): "1"})
        _control_properties(properties)
        degree = SubElement(radical, M("deg"))
        if node["degree"] is not None:
            _emit_node(degree, node["degree"])
        radicand = SubElement(radical, M("e"))
        _emit_node(radicand, node["radicand"])
        return
    if kind == "nary":
        _emit_nary(parent, node)
        return
    if kind == "matrix":
        matrix = SubElement(parent, M("m"))
        properties = SubElement(matrix, M("mPr"))
        SubElement(properties, M("baseJc"), {M("val"): "center"})
        _control_properties(properties)
        for row in node["rows"]:
            matrix_row = SubElement(matrix, M("mr"))
            for cell in row:
                entry = SubElement(matrix_row, M("e"))
                _emit_node(entry, cell)
        return
    raise AssertionError(f"unhandled equation node: {kind}")


def _emit_script(parent: Element, node: dict[str, Any]) -> None:
    tags = {
        "subscript": ("sSub", "sSubPr"),
        "superscript": ("sSup", "sSupPr"),
        "subsuperscript": ("sSubSup", "sSubSupPr"),
    }
    script_tag, properties_tag = tags[node["type"]]
    script = SubElement(parent, M(script_tag))
    _control_properties(SubElement(script, M(properties_tag)))
    _emit_node(SubElement(script, M("e")), node["base"])
    if node["type"] in {"subscript", "subsuperscript"}:
        _emit_node(SubElement(script, M("sub")), node["subscript"])
    if node["type"] in {"superscript", "subsuperscript"}:
        _emit_node(SubElement(script, M("sup")), node["exponent"])


def _emit_nary(parent: Element, node: dict[str, Any]) -> None:
    nary = SubElement(parent, M("nary"))
    properties = SubElement(nary, M("naryPr"))
    SubElement(properties, M("chr"), {M("val"): "∑"})
    SubElement(properties, M("limLoc"), {M("val"): "undOvr"})
    _control_properties(properties)
    lower = SubElement(nary, M("sub"))
    upper = SubElement(nary, M("sup"))
    operand = SubElement(nary, M("e"))
    if node["lower"] is not None:
        _emit_node(lower, node["lower"])
    if node["upper"] is not None:
        _emit_node(upper, node["upper"])
    _math_run(operand, "")


def _math_run(parent: Element, value: str) -> None:
    run = SubElement(parent, M("r"))
    _drawing_run_properties(run)
    text = SubElement(run, M("t"))
    if value.startswith(" ") or value.endswith(" "):
        text.set(XML_SPACE, "preserve")
    text.text = value


def _drawing_run_properties(parent: Element) -> Element:
    properties = SubElement(parent, A("rPr"), {"lang": "en-US", "smtClean": "0"})
    SubElement(properties, A("latin"), {"typeface": "Cambria Math"})
    return properties


def _control_properties(parent: Element) -> None:
    control = SubElement(parent, M("ctrlPr"))
    _drawing_run_properties(control)


__all__ = ["build_equation"]
