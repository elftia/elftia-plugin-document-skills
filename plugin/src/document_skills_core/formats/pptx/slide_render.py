"""Build a private one-slide PPTX candidate without mutating the source package."""

from pathlib import Path
from xml.etree.ElementTree import tostring

from defusedxml.ElementTree import fromstring

from .constants import NS
from .package import OpcPackage, write_deterministic_zip


def write_single_slide_candidate(
    package: OpcPackage,
    slide: int,
    destination: Path,
) -> Path:
    presentation = fromstring(package.parts["ppt/presentation.xml"])
    slide_list = presentation.find(f"{{{NS['p']}}}sldIdLst")
    if slide_list is None or not 1 <= slide <= len(slide_list):
        raise ValueError("PPTX slide list does not contain the requested render slide.")
    selected = list(slide_list)[slide - 1]
    for child in list(slide_list):
        if child is not selected:
            slide_list.remove(child)
    parts = dict(package.parts)
    parts["ppt/presentation.xml"] = tostring(
        presentation,
        encoding="UTF-8",
        xml_declaration=True,
    )
    write_deterministic_zip(destination, parts)
    return destination
