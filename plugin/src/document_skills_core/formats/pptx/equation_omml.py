"""Facade for native editable Office Math construction and readback."""

from .equation_omml_emit import build_equation
from .equation_omml_read import is_equation_element, project_equation

__all__ = ["build_equation", "is_equation_element", "project_equation"]
