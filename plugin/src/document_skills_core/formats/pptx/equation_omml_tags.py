"""Namespace helpers shared by Office Math emission and readback."""

from .constants import NS


_P = NS["p"]
_A = NS["a"]
_A14 = NS["a14"]
_M = NS["m"]
_MC = NS["mc"]
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def P(tag: str) -> str:
    return f"{{{_P}}}{tag}"


def A(tag: str) -> str:
    return f"{{{_A}}}{tag}"


def A14(tag: str) -> str:
    return f"{{{_A14}}}{tag}"


def M(tag: str) -> str:
    return f"{{{_M}}}{tag}"


def MC(tag: str) -> str:
    return f"{{{_MC}}}{tag}"


__all__ = ["A", "A14", "M", "MC", "P", "XML_SPACE"]
