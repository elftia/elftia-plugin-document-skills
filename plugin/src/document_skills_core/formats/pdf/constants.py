"""PDF byte-format constants, limits, and page-box names.

Module provenance: original Elftia-authored clean-room constants derived from
independently-authored ISO 32000-1/2 structural requirements.  No code from
pypdf, PyMuPDF, fpdf2, reportlab, or pdf-lib is incorporated.
"""

# Header / trailer markers
PDF_HEADER_MAGIC = b"%PDF-"
PDF_EOF_MARKER = b"%%EOF"
PDF_HEADER_RE = b"%PDF-(\\d+)\\.(\\d+)"

# Archive / byte-format limits (reuse foundation ArchiveLimits *concept*, not ZIP)
MAX_PDF_BYTES = 128 * 1024 * 1024
MAX_UNCOMPRESSED_STREAM_BYTES = 512 * 1024 * 1024
MAX_EXPANSION_RATIO = 200.0
MAX_STREAM_BYTES = 64 * 1024 * 1024
MAX_OBJECTS = 2_000_000
MAX_XREF_ENTRIES = 2_000_000
MAX_OBJECT_GRAPH_DEPTH = 64
MAX_DECODE_FILTER_CHAIN_DEPTH = 8
MAX_STREAM_COUNT = 100_000
MAX_CONTENT_STREAM_OPERATORS = 500_000

# Operation argument limits
MAX_ARGUMENT_TEXT = 64_000
MAX_PAGES = 10_000
MAX_BLOCKS_PER_PAGE = 5_000
MAX_EDIT_PRIMITIVES = 64
MAX_REWRITE_BLOCKS = 256
MAX_TABLE_ROWS = 500
MAX_TABLE_COLS = 50

# Canonical page-box names (ISO 32000 Table 30)
MEDIA_BOX = "/MediaBox"
CROP_BOX = "/CropBox"
BLEED_BOX = "/BleedBox"
TRIM_BOX = "/TrimBox"
ART_BOX = "/ArtBox"
PAGE_BOX_NAMES = (MEDIA_BOX, CROP_BOX, BLEED_BOX, TRIM_BOX, ART_BOX)

# Canonical page sizes in points (1/72 inch)
PAGE_SIZES = {
    "A4": (595.276, 841.89),
    "Letter": (612.0, 792.0),
    "Legal": (612.0, 1008.0),
}

# Decode filters we support (bounded)
SUPPORTED_FILTERS = frozenset({
    "FlateDecode",
    "ASCIIHexDecode",
    "ASCII85Decode",
    "LZWDecode",
    "RunLengthDecode",
    "DCTDecode",
})

# Font type names
FONT_TYPES = frozenset({"Type0", "Type1", "TrueType", "CFF", "CIDFontType0", "CIDFontType2"})

# Annotation subtypes we inventory
ANNOTATION_SUBTYPES = frozenset({
    "Link", "Text", "Stamp", "Highlight", "Underline", "Squiggly",
    "StrikeOut", "Widget", "Popup", "Circle", "Square", "FileAttachment",
    "Ink", "FreeText", "Line", "Polygon", "PolyLine", "Caret", "Redact",
    "TrapNet", "Watermark", "3D", "Sound", "Movie", "Screen",
})

# AcroForm field types
FIELD_TYPES = frozenset({
    "text", "checkbox", "radio", "list", "choice", "signature", "button",
})
