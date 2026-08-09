"""WordprocessingML and OPC constants used by the Core DOCX package."""

from xml.etree.ElementTree import QName, register_namespace

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rels": "http://schemas.openxmlformats.org/package/2006/relationships",
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

for _prefix, _uri in NS.items():
    register_namespace(_prefix, _uri)

CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
register_namespace("", CONTENT_TYPES_NS)

REL_OFFICE_DOCUMENT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
REL_CORE_PROPERTIES = (
    "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
)
REL_EXTENDED_PROPERTIES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties"
)
REL_STYLES = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
REL_NUMBERING = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
)
REL_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
REL_HEADER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header"
REL_FOOTER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer"
REL_HYPERLINK = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
)
REL_ATTACHED_TEMPLATE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate"
)

WORD_MAIN = "word/document.xml"
CONTENT_TYPES = "[Content_Types].xml"
PACKAGE_RELS = "_rels/.rels"

MAX_DOCX_BYTES = 128 * 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_PARTS = 5_000
MAX_TEXT_CHARS = 1_000_000
MAX_RESULT_ITEMS = 10_000
CT_HEADER = "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"
CT_FOOTER = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"

MAX_ARGUMENT_TEXT = 64_000
MAX_RULES = 256
MAX_VARIABLES = 512

# Half-point run sizes for Heading1..HeadingN, indexed by level - 1. The first
# two match what Core DOCX has always emitted; the rest continue the ramp down
# toward body size, so a thesis-style 1.1.1 outline is expressible without a
# caller flattening its own structure.
HEADING_SIZES = ("32", "28", "26", "24", "22", "22")
MAX_HEADING_LEVEL = len(HEADING_SIZES)
# Word documents conventionally carry at least the Heading1/Heading2 pair, and
# emitting them unconditionally keeps packages whose headings stop at level 1
# byte-identical to the ones earlier versions produced.
MIN_HEADING_STYLES = 2


def qn(prefix: str, local: str) -> str:
    return str(QName(NS[prefix], local))


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
