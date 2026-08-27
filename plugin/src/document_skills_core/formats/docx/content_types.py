"""Strict OPC content-type parsing and Word package identity checks."""

from defusedxml.ElementTree import fromstring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

from .constants import CONTENT_TYPES_NS, WORD_MAIN
from .relationships import Relationship

WORD_DOCUMENT_MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document.main+xml"
)
WORD_TEMPLATE_MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.template.main+xml"
)
WORD_MACRO_ENABLED_MAIN_CONTENT_TYPE = (
    "application/vnd.ms-word.document.macroEnabled.main+xml"
)


def parse_content_types(payload: bytes) -> dict[str, str]:
    root = fromstring(payload)
    if root.tag != f"{{{CONTENT_TYPES_NS}}}Types":
        _unsafe("Invalid OPC content-types root.")
    result: dict[str, str] = {}
    override_identities: dict[tuple[str, ...], str] = {}
    for node in root:
        content_type = node.attrib.get("ContentType", "")
        if node.tag == f"{{{CONTENT_TYPES_NS}}}Override":
            key = _override_key(
                node.attrib.get("PartName", ""),
                override_identities,
            )
        elif node.tag == f"{{{CONTENT_TYPES_NS}}}Default":
            key = _default_key(node.attrib.get("Extension", ""))
        else:
            _unsafe("Unknown OPC content-type declaration.")
        if not key or not content_type or key in result:
            _unsafe("Invalid or duplicate OPC content-type entry.", key=key)
        result[key] = content_type
    return dict(sorted(result.items()))


def validate_package_content_types(
    content_types: dict[str, str],
    relationships: list[Relationship],
    *,
    allow_template_main: bool = False,
) -> None:
    office_documents = [
        item
        for item in relationships
        if item.source_part == ""
        and item.relationship_type.rsplit("/", 1)[-1] == "officeDocument"
    ]
    if (
        len(office_documents) != 1
        or office_documents[0].resolved_target != WORD_MAIN
    ):
        _unsafe("Package root must identify one contained Word main document.")
    main_type = content_type_for(WORD_MAIN, content_types) or ""
    accepted = {WORD_DOCUMENT_MAIN_CONTENT_TYPE}
    if allow_template_main:
        accepted.add(WORD_TEMPLATE_MAIN_CONTENT_TYPE)
    accepted.add(WORD_MACRO_ENABLED_MAIN_CONTENT_TYPE)
    if main_type not in accepted:
        _unsafe("Word main document has an invalid content type.", content_type=main_type)


def content_type_for(name: str, content_types: dict[str, str]) -> str | None:
    direct = content_types.get(f"/{name}")
    if direct is not None:
        return direct
    terminal = name.rsplit("/", 1)[-1]
    suffix = terminal.rsplit(".", 1)[-1].casefold() if "." in terminal else ""
    return content_types.get(f"*.{suffix}") if suffix else None


def _override_key(
    raw: str,
    identities: dict[tuple[str, ...], str],
) -> str:
    if not raw.startswith("/") or raw.startswith("//") or "\\" in raw:
        _unsafe("Invalid OPC content-type override path.", part=raw)
    try:
        identity = PORTABLE_PATH_POLICY.parse_relative(raw[1:])
    except (TypeError, UnicodeError, ValueError) as error:
        _unsafe(
            "OPC content-type override path is not portable.",
            part=raw,
            reason=type(error).__name__,
        )
    if identity.keys in identities:
        _unsafe(
            "Duplicate or normalized-alias OPC content-type override.",
            part=raw,
            alias_of=identities[identity.keys],
        )
    key = f"/{'/'.join(identity.components)}"
    identities[identity.keys] = key
    return key


def _default_key(extension: str) -> str:
    if not extension or any(marker in extension for marker in ("/", "\\", ".")):
        _unsafe("Invalid OPC content-type extension.", extension=extension)
    try:
        normalized = PORTABLE_PATH_POLICY.component_key(extension)
    except (TypeError, UnicodeError, ValueError) as error:
        _unsafe(
            "OPC content-type extension is not portable.",
            extension=extension,
            reason=type(error).__name__,
        )
    return f"*.{normalized}"


def _unsafe(message: str, **details: object) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)
