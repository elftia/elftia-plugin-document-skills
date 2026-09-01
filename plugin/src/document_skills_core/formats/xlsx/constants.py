"""SpreadsheetML and OPC constants used by the Core XLSX package."""

from xml.etree.ElementTree import QName, register_namespace

NS = {
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rels": "http://schemas.openxmlformats.org/package/2006/relationships",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "x14": "http://schemas.openxmlformats.org/spreadsheetml/2006/9/main",
    "xm": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "xr": "http://schemas.microsoft.com/office/spreadsheetml/2014/revision",
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
REL_SHARED_STRINGS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
)
REL_STYLES = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
REL_WORKSHEET = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
)
REL_CALC_CHAIN = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/calcChain"
)
REL_TABLE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/table"
REL_HYPERLINK = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
)
REL_DRAWING = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"
)
REL_CHART = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart"
REL_COMMENTS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
REL_VML_DRAWING = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/vmlDrawing"
)
REL_PIVOT_TABLE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotTable"
)
REL_PIVOT_CACHE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotCacheDefinition"
)
REL_EXTERNAL_LINK = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLink"
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
WORKBOOK_MAIN = "xl/workbook.xml"
WORKBOOK_RELS = "xl/_rels/workbook.xml.rels"
STYLES_PART = "xl/styles.xml"
SHARED_STRINGS_PART = "xl/sharedStrings.xml"
CALC_CHAIN_PART = "xl/calcChain.xml"

# SpreadsheetML workbook main content types
CONTENT_TYPE_XLSX = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
)
CONTENT_TYPE_XLTX = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml"
)
CONTENT_TYPE_XLSM = "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
CONTENT_TYPE_XLTM = "application/vnd.ms-excel.template.macroEnabled.main+xml"
WORKBOOK_CONTENT_TYPES = {
    "xlsx": CONTENT_TYPE_XLSX,
    "xltx": CONTENT_TYPE_XLTX,
    "xlsm": CONTENT_TYPE_XLSM,
    "xltm": CONTENT_TYPE_XLTM,
}

# Archive limits
MAX_XLSX_BYTES = 128 * 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_PARTS = 5_000

# Operation argument limits
MAX_ARGUMENT_TEXT = 64_000
MAX_ROWS = 10_000
MAX_CELLS_PER_SHEET = 100_000
MAX_SHEETS = 1_000
MAX_TABLES = 500
MAX_DEFINED_NAMES = 1_000
MAX_HYPERLINKS = 1_000
MAX_COMMENTS = 1_000
MAX_EDIT_OPS = 256

# Formula state enum
FORMULA_STATE_RECALCULATED = "recalculated"
FORMULA_STATE_STALE = "stale"
FORMULA_STATE_NEVER_CALCULATED = "never_calculated"
FORMULA_STATE_RECALCULATION_REQUIRED = "recalculation_required"
FORMULA_STATES = frozenset(
    {
        FORMULA_STATE_RECALCULATED,
        FORMULA_STATE_STALE,
        FORMULA_STATE_NEVER_CALCULATED,
        FORMULA_STATE_RECALCULATION_REQUIRED,
    }
)


def qn(prefix: str, local: str) -> str:
    """Build a qualified name from a namespace prefix and local name."""
    return str(QName(NS[prefix], local))


def local_name(tag: str) -> str:
    """Extract the local name from a qualified XML tag."""
    return tag.rsplit("}", 1)[-1]
