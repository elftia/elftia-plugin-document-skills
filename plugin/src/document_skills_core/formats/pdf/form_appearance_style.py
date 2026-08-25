"""Validated DA, MK, BS, and field-flag subset for form appearances."""

from dataclasses import dataclass
import math
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_layout import pdf_number
from .object_model import PdfDict


@dataclass(frozen=True)
class DefaultAppearance:
    font_size: float
    color: tuple[float, ...]


@dataclass(frozen=True)
class WidgetStyle:
    background: tuple[float, ...] | None
    border: tuple[float, ...]
    border_width: float


def parse_default_appearance(value: Any) -> DefaultAppearance:
    if not isinstance(value, str):
        unsupported("Text/choice flatten requires an inherited default appearance string.")
    tokens = value.split()
    if (
        len(tokens) == 5
        and tokens[0] == "/Helv"
        and tokens[2] == "Tf"
        and tokens[4] == "g"
    ):
        font_size = _number(tokens[1], "default appearance font size")
        color = (_unit_number(tokens[3], "default appearance color"),)
    elif (
        len(tokens) == 7
        and tokens[0] == "/Helv"
        and tokens[2] == "Tf"
        and tokens[6] == "rg"
    ):
        font_size = _number(tokens[1], "default appearance font size")
        color = tuple(
            _unit_number(token, "default appearance color")
            for token in tokens[3:6]
        )
    else:
        unsupported("Default appearance operators are outside the supported /Helv subset.")
    if font_size <= 0:
        unsupported("Automatic or non-positive default appearance font sizes are unsupported.")
    return DefaultAppearance(font_size, color)


def parse_widget_style(widget: PdfDict) -> WidgetStyle:
    if widget.get("/H") not in (None, "/N"):
        unsupported("Non-default widget highlight modes are unsupported.")
    mk = widget.get("/MK")
    background = None
    border_color = None
    if mk is not None:
        if not isinstance(mk, PdfDict) or set(mk.entries) - {"/BG", "/BC"}:
            unsupported("Widget MK entries are outside the supported BG/BC subset.")
        background = _color(mk.get("/BG"), "widget background")
        border_color = _color(mk.get("/BC"), "widget border")
    bs = widget.get("/BS")
    border = widget.get("/Border")
    if bs is not None and border is not None:
        unsupported("Simultaneous BS and Border styling is ambiguous.")
    width = 1.0
    if bs is not None:
        if not isinstance(bs, PdfDict) or set(bs.entries) - {"/W", "/S"}:
            unsupported("Widget BS entries are outside the supported solid subset.")
        if bs.get("/S", "/S") != "/S":
            unsupported("Only solid widget borders are supported.")
        width = _numeric_value(bs.get("/W", 1), "widget border width")
    elif border is not None:
        if not isinstance(border, list) or len(border) != 3:
            unsupported("Only three-number widget Border arrays are supported.")
        horizontal = _numeric_value(border[0], "widget border horizontal radius")
        vertical = _numeric_value(border[1], "widget border vertical radius")
        if horizontal != 0 or vertical != 0:
            unsupported("Rounded widget borders are unsupported.")
        width = _numeric_value(border[2], "widget border width")
    if width < 0:
        unsupported("Widget border width cannot be negative.")
    return WidgetStyle(background, border_color or (0.0,), width)


def require_supported_field_flags(field_type: str, flags: int) -> None:
    base_flags = 1 | 2 | 4
    if field_type == "/Tx" and flags & ~base_flags:
        unsupported("Multiline, password, comb, and rich-text fields are unsupported.")
    if field_type == "/Ch":
        combo_flag = 131072
        if not flags & combo_flag or flags & ~(base_flags | combo_flag):
            unsupported("Only non-editable single-select combo choice fields are supported.")


def color_operator(color: tuple[float, ...], *, stroke: bool) -> str:
    values = " ".join(pdf_number(component) for component in color)
    operator = ("G" if stroke else "g") if len(color) == 1 else ("RG" if stroke else "rg")
    return f"{values} {operator}"


def escape_pdf_string(value: str) -> str:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _color(value: Any, label: str) -> tuple[float, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) not in {1, 3}:
        unsupported(f"{label.capitalize()} requires a DeviceGray or DeviceRGB color.")
    return tuple(_unit_value(component, label) for component in value)


def _number(value: str, label: str) -> float:
    try:
        number = float(value)
    except ValueError:
        unsupported(f"{label.capitalize()} is not numeric.")
    if not math.isfinite(number):
        unsupported(f"{label.capitalize()} is not finite.")
    return number


def _unit_number(value: str, label: str) -> float:
    return _unit_value(_number(value, label), label)


def _numeric_value(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        unsupported(f"{label.capitalize()} is not numeric.")
    number = float(value)
    if not math.isfinite(number):
        unsupported(f"{label.capitalize()} is not finite.")
    return number


def _unit_value(value: Any, label: str) -> float:
    number = _numeric_value(value, label)
    if number < 0 or number > 1:
        unsupported(f"{label.capitalize()} must be between zero and one.")
    return number


def unsupported(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": "pdf.form-appearance"},
    )
