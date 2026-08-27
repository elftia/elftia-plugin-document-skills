"""PresentationML and OPC constants used by the Core PPTX package."""

from xml.etree.ElementTree import QName, register_namespace

NS = {
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rels": "http://schemas.openxmlformats.org/package/2006/relationships",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "a14": "http://schemas.microsoft.com/office/drawing/2010/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r14": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}

for _prefix, _uri in NS.items():
    register_namespace(_prefix, _uri)

CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
register_namespace("", CONTENT_TYPES_NS)

# OPC relationship types
REL_OFFICE_DOCUMENT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
REL_CORE_PROPERTIES = (
    "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
)
REL_EXTENDED_PROPERTIES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties"
)
REL_SLIDE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
)
REL_SLIDE_LAYOUT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
)
REL_SLIDE_MASTER = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
)
REL_THEME = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
)
REL_NOTES_MASTER = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster"
)
REL_NOTES_SLIDE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"
)
REL_SLIDE_RELS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
)
REL_IMAGE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)
REL_CHART = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart"
)
REL_HYPERLINK = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
)
REL_TABLE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/table"
)
REL_MEDIA = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/media"
)
REL_VBA_PROJECT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/vbaProject"
)
REL_ATTACHED_TEMPLATE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate"
)

# Canonical part paths
CONTENT_TYPES = "[Content_Types].xml"
PACKAGE_RELS = "_rels/.rels"
PRESENTATION_MAIN = "ppt/presentation.xml"
PRESENTATION_RELS = "ppt/_rels/presentation.xml.rels"

# Archive limits
MAX_PPTX_BYTES = 128 * 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_PARTS = 5_000

# Operation argument limits
MAX_ARGUMENT_TEXT = 64_000
MAX_SLIDES = 1_000
MAX_SHAPES_PER_SLIDE = 500
MAX_RUNS_PER_TEXT_FRAME = 1_000
MAX_EDIT_OPS = 256


def qn(prefix: str, local: str) -> str:
    """Build a qualified name from a namespace prefix and local name."""
    return str(QName(NS[prefix], local))


def local_name(tag: str) -> str:
    """Extract the local name from a qualified XML tag."""
    return tag.rsplit("}", 1)[-1]
