"""Generated scene-package OPC relationship and content-type checks."""

from .package import OpcPackage

_EXPECTED_PART_TYPES = (
    (
        "docProps/core.xml",
        "application/vnd.openxmlformats-package.core-properties+xml",
        True,
    ),
    (
        "docProps/app.xml",
        "application/vnd.openxmlformats-officedocument.extended-properties+xml",
        True,
    ),
    ("ppt/presentation.xml", "presentationml.presentation.main+xml", False),
    ("ppt/slideMasters/slideMaster", "presentationml.slideMaster+xml", False),
    ("ppt/slideLayouts/slideLayout", "presentationml.slideLayout+xml", False),
    ("ppt/slides/slide", "presentationml.slide+xml", False),
    ("ppt/theme/theme", "officedocument.theme+xml", False),
)
_RELATIONSHIP_TYPE_SUFFIXES = {
    "core-properties": "package.core-properties+xml",
    "extended-properties": "officedocument.extended-properties+xml",
    "officeDocument": "presentationml.presentation.main+xml",
    "slide": "presentationml.slide+xml",
    "slideLayout": "presentationml.slideLayout+xml",
    "slideMaster": "presentationml.slideMaster+xml",
    "theme": "officedocument.theme+xml",
}
_ALLOWED_RELATIONSHIP_TERMINALS = set(_RELATIONSHIP_TYPE_SUFFIXES) | {"image"}


def generated_scene_opc_failures(package: OpcPackage) -> list[str]:
    """Return bounded failures for the exact OPC vocabulary emitted by scenes."""
    failures: list[str] = []
    for name in sorted(package.parts):
        content_type = package.content_type_for(name) or ""
        if name.startswith("ppt/media/"):
            if not content_type.casefold().startswith("image/"):
                failures.append(f"content-type:{name}")
            continue
        for prefix, expected, exact in _EXPECTED_PART_TYPES:
            if name == prefix or (not exact and name.startswith(prefix)):
                valid_type = (
                    content_type == expected
                    if exact
                    else content_type.endswith(expected)
                )
                if not valid_type:
                    failures.append(f"content-type:{name}")
                break

    for relationship in package.relationships:
        terminal = relationship.relationship_type.rsplit("/", 1)[-1]
        target = relationship.resolved_target
        if relationship.target_mode != "Internal" or target is None:
            failures.append(f"relationship-external:{relationship.relationship_id}")
            continue
        if terminal not in _ALLOWED_RELATIONSHIP_TERMINALS:
            failures.append(f"relationship-type:{relationship.relationship_id}")
            continue
        content_type = package.content_type_for(target) or ""
        if terminal == "image":
            valid_type = content_type.casefold().startswith("image/")
        else:
            valid_type = content_type.endswith(_RELATIONSHIP_TYPE_SUFFIXES[terminal])
        if not valid_type:
            failures.append(f"relationship-content-type:{relationship.relationship_id}")
    return failures[:64]
