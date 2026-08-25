"""Safe deterministic XMP creation and bounded metadata reconciliation.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
import xml.etree.ElementTree as ET

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_model import IndirectReference, PdfDict, PdfObject, PdfObjectModel

_XMP = "adobe:ns:meta/"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_DC = "http://purl.org/dc/elements/1.1/"
_PDF = "http://ns.adobe.com/pdf/1.3/"
_XML = "http://www.w3.org/XML/1998/namespace"
_MAX_XMP_BYTES = 8 * 1024 * 1024
_FIELDS = ("title", "author", "subject", "keywords")

for _prefix, _uri in (("x", _XMP), ("rdf", _RDF), ("dc", _DC), ("pdf", _PDF)):
    ET.register_namespace(_prefix, _uri)


@dataclass(frozen=True)
class LinkedXmp:
    """One Catalog-linked, unfiltered XML metadata stream."""

    obj: PdfObject
    dictionary: PdfDict
    xml: bytes


def load_linked_xmp(model: PdfObjectModel) -> LinkedXmp | None:
    """Resolve only the Catalog's Metadata reference and validate safe shape."""
    catalog = model.get_object(model.catalog_ref).value
    if not isinstance(catalog, PdfDict):
        _unsafe("PDF Catalog is not a dictionary.")
    reference = catalog.get("/Metadata")
    if reference is None:
        return None
    if not isinstance(reference, IndirectReference):
        _unsafe("PDF Catalog Metadata must be an indirect reference.")
    obj = model.get_object(reference)
    if obj.gen_num != reference.gen_num:
        _unsafe("PDF Catalog Metadata reference generation is inconsistent.")
    if not isinstance(obj.value, tuple) or len(obj.value) != 2:
        _unsafe("Catalog-linked PDF Metadata is not a stream.")
    dictionary, xml = obj.value
    if not isinstance(dictionary, PdfDict) or not isinstance(xml, bytes):
        _unsafe("Catalog-linked PDF Metadata stream is malformed.")
    if dictionary.get("/Type") != "/Metadata" or dictionary.get("/Subtype") != "/XML":
        _unsupported("Catalog-linked Metadata is not an XMP XML stream.")
    if dictionary.get("/Filter") is not None or dictionary.get("/DecodeParms") is not None:
        _unsupported("Filtered XMP streams cannot be reconciled safely.")
    if not isinstance(dictionary.get("/Length"), int):
        _unsupported("XMP stream Length must be a direct integer.")
    return LinkedXmp(obj=obj, dictionary=dictionary, xml=xml)


def build_xmp(metadata: dict[str, str]) -> bytes:
    """Build deterministic UTF-8 XMP for the supported Info fields."""
    root = ET.Element(_tag(_XMP, "xmpmeta"))
    rdf = ET.SubElement(root, _tag(_RDF, "RDF"))
    description = ET.SubElement(rdf, _tag(_RDF, "Description"))
    description.set(_tag(_RDF, "about"), "")
    _write_metadata(description, metadata)
    return _serialize(root)


def update_xmp(xml: bytes, metadata: dict[str, str]) -> bytes:
    """Update supported fields while retaining unknown elements and attributes."""
    root = _parse_root(xml)
    rdf_nodes = [child for child in root if child.tag == _tag(_RDF, "RDF")]
    if len(rdf_nodes) != 1:
        _unsupported("XMP must contain exactly one RDF root.")
    rdf = rdf_nodes[0]
    descriptions = [
        child for child in rdf if child.tag == _tag(_RDF, "Description")
    ]
    known = [description for description in descriptions if _has_known_field(description)]
    if len(known) > 1:
        _unsupported("XMP metadata fields span multiple RDF descriptions.")
    if known:
        description = known[0]
    elif len(descriptions) == 1:
        description = descriptions[0]
    else:
        description = ET.SubElement(rdf, _tag(_RDF, "Description"))
        description.set(_tag(_RDF, "about"), "")
    _write_metadata(description, metadata)
    return _serialize(root)


def read_xmp_metadata(xml: bytes) -> dict[str, str]:
    """Read the supported XMP fields from one unambiguous description."""
    root = _parse_root(xml)
    descriptions = [
        description
        for rdf in root
        if rdf.tag == _tag(_RDF, "RDF")
        for description in rdf
        if description.tag == _tag(_RDF, "Description")
        and _has_known_field(description)
    ]
    if len(descriptions) > 1:
        _unsupported("XMP metadata fields span multiple RDF descriptions.")
    if not descriptions:
        return {}
    description = descriptions[0]
    result: dict[str, str] = {}
    title = _read_alt(description, "title")
    author = _read_author(description)
    subject = _read_alt(description, "description")
    keywords = _read_simple(description, _tag(_PDF, "Keywords"))
    for field, value in (
        ("title", title),
        ("author", author),
        ("subject", subject),
        ("keywords", keywords),
    ):
        if value is not None:
            result[field] = value
    return result


def _write_metadata(description: ET.Element, metadata: dict[str, str]) -> None:
    values = {field: metadata.get(field, "") for field in _FIELDS}
    _set_alt(description, "title", values["title"])
    _set_author(description, values["author"])
    _set_alt(description, "description", values["subject"])
    _set_simple(description, _tag(_PDF, "Keywords"), values["keywords"])


def _set_alt(description: ET.Element, local: str, value: str) -> None:
    field = _single_child(description, _tag(_DC, local), create=True)
    assert field is not None
    alt = _single_child(field, _tag(_RDF, "Alt"), create=True)
    assert alt is not None
    invalid = [child for child in field if child is not alt]
    if invalid:
        _unsupported(f"XMP dc:{local} has an unsupported value shape.")
    defaults = [
        child
        for child in alt
        if child.tag == _tag(_RDF, "li")
        and child.get(_tag(_XML, "lang")) == "x-default"
    ]
    if len(defaults) > 1:
        _unsupported(f"XMP dc:{local} has duplicate x-default values.")
    if defaults:
        item = defaults[0]
    else:
        item = ET.SubElement(alt, _tag(_RDF, "li"))
        item.set(_tag(_XML, "lang"), "x-default")
    item.text = value


def _set_author(description: ET.Element, value: str) -> None:
    field = _single_child(description, _tag(_DC, "creator"), create=True)
    assert field is not None
    sequence = _single_child(field, _tag(_RDF, "Seq"), create=True)
    assert sequence is not None
    if any(child is not sequence for child in field):
        _unsupported("XMP dc:creator has an unsupported value shape.")
    authors = [child for child in sequence if child.tag == _tag(_RDF, "li")]
    if len(authors) > 1 or any(child.tag != _tag(_RDF, "li") for child in sequence):
        _unsupported("Multiple XMP creators cannot be represented by PDF Info Author.")
    item = authors[0] if authors else ET.SubElement(sequence, _tag(_RDF, "li"))
    item.text = value


def _set_simple(description: ET.Element, tag: str, value: str) -> None:
    field = _single_child(description, tag, create=True)
    assert field is not None
    if list(field):
        _unsupported("XMP simple metadata field contains nested content.")
    field.text = value


def _read_alt(description: ET.Element, local: str) -> str | None:
    field = _single_child(description, _tag(_DC, local), create=False)
    if field is None:
        return None
    alt = _single_child(field, _tag(_RDF, "Alt"), create=False)
    if alt is None:
        _unsupported(f"XMP dc:{local} is not an RDF Alt value.")
    defaults = [
        child
        for child in alt
        if child.tag == _tag(_RDF, "li")
        and child.get(_tag(_XML, "lang")) == "x-default"
    ]
    if len(defaults) != 1:
        _unsupported(f"XMP dc:{local} must have one x-default value.")
    return defaults[0].text or ""


def _read_author(description: ET.Element) -> str | None:
    field = _single_child(description, _tag(_DC, "creator"), create=False)
    if field is None:
        return None
    sequence = _single_child(field, _tag(_RDF, "Seq"), create=False)
    if sequence is None:
        _unsupported("XMP dc:creator is not an RDF Seq value.")
    authors = [child for child in sequence if child.tag == _tag(_RDF, "li")]
    if len(authors) != 1:
        _unsupported("XMP dc:creator must contain one author.")
    return authors[0].text or ""


def _read_simple(description: ET.Element, tag: str) -> str | None:
    field = _single_child(description, tag, create=False)
    if field is None:
        return None
    if list(field):
        _unsupported("XMP simple metadata field contains nested content.")
    return field.text or ""


def _single_child(
    parent: ET.Element,
    tag: str,
    *,
    create: bool,
) -> ET.Element | None:
    matches = [child for child in parent if child.tag == tag]
    if len(matches) > 1:
        _unsupported("XMP contains duplicate supported metadata elements.")
    if matches:
        return matches[0]
    return ET.SubElement(parent, tag) if create else None


def _has_known_field(description: ET.Element) -> bool:
    known = {
        _tag(_DC, "title"),
        _tag(_DC, "creator"),
        _tag(_DC, "description"),
        _tag(_PDF, "Keywords"),
    }
    return any(child.tag in known for child in description)


def _parse_root(xml: bytes) -> ET.Element:
    if len(xml) > _MAX_XMP_BYTES:
        _unsupported("XMP stream exceeds the reconciliation byte bound.")
    upper = xml.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        _unsupported("XMP DTD and entity declarations are not accepted.")
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
        root = ET.fromstring(xml, parser=parser)
    except ET.ParseError as error:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Catalog-linked XMP is not well-formed XML.",
        ) from error
    if root.tag != _tag(_XMP, "xmpmeta"):
        _unsupported("XMP root must be x:xmpmeta.")
    return root


def _serialize(root: ET.Element) -> bytes:
    body = ET.tostring(root, encoding="utf-8", short_empty_elements=False)
    return (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'.encode("utf-8")
        + body
        + b'\n<?xpacket end="w"?>'
    )


def _tag(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)


def _unsupported(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": "pdf.xmp-metadata-reconciliation"},
    )
