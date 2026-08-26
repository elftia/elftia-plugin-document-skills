"""Plan, apply, and reopen-check explicit Word style overlays."""

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import ArtifactRecord

from .constants import NS, qn
from .package import OpcPackage
from .xml_utils import xml_bytes

STYLES_PART = "word/styles.xml"
_DEPENDENCY_ELEMENTS = ("basedOn", "link", "next")
_STYLE_TYPES = {"character", "numbering", "paragraph", "table"}


@dataclass(frozen=True)
class StyleOverlayPlan:
    conflict_policy: str
    requested: tuple[str, ...]
    imported: tuple[str, ...]
    replaced: tuple[str, ...]
    kept: tuple[str, ...]
    styles_payload: bytes | None
    expected_styles_sha256: str

    @property
    def changed_parts(self) -> dict[str, bytes]:
        return (
            {STYLES_PART: self.styles_payload}
            if self.styles_payload is not None
            else {}
        )

    def as_dict(self, source: ArtifactRecord) -> dict[str, Any]:
        return {
            "source": {
                "path": source.path,
                "sha256": source.sha256,
                "bytes": source.bytes,
            },
            "conflict_policy": self.conflict_policy,
            "requested_style_ids": list(self.requested),
            "imported_style_ids": list(self.imported),
            "replaced_style_ids": list(self.replaced),
            "kept_style_ids": list(self.kept),
        }


def plan_style_overlay(
    base: OpcPackage,
    overlay: OpcPackage,
    request: dict[str, Any],
) -> StyleOverlayPlan:
    base_root = base.xml(STYLES_PART)
    overlay_root = overlay.xml(STYLES_PART)
    base_styles = _style_map(base_root, "base")
    overlay_styles = _style_map(overlay_root, "overlay")
    requested = request["style_ids"]
    missing = sorted(set(requested) - set(overlay_styles))
    if missing:
        _precondition_failed("style-id-missing", style_ids=missing)
    policy = request["conflict_policy"]
    imported = tuple(style_id for style_id in requested if style_id not in base_styles)
    kept = tuple(
        style_id
        for style_id in requested
        if style_id in base_styles and policy == "keep-base"
    )
    replaced = tuple(
        style_id
        for style_id in requested
        if style_id in base_styles and policy == "replace-existing"
    )
    effective = imported + replaced
    available = set(base_styles) | set(effective)
    for style_id in effective:
        _validate_selected_style(overlay_styles[style_id], style_id, available)
    for style_id in replaced:
        existing = base_styles[style_id]
        position = list(base_root).index(existing)
        base_root.remove(existing)
        base_root.insert(position, deepcopy(overlay_styles[style_id]))
    for style_id in imported:
        base_root.append(deepcopy(overlay_styles[style_id]))
    payload = xml_bytes(base_root) if effective else None
    expected = sha256(payload or base.parts[STYLES_PART]).hexdigest()
    return StyleOverlayPlan(
        policy,
        requested,
        imported,
        replaced,
        kept,
        payload,
        expected,
    )


def assert_style_overlay(path: Path, plan: StyleOverlayPlan) -> dict[str, Any]:
    package = OpcPackage.open(path)
    if package.part_hashes.get(STYLES_PART) != plan.expected_styles_sha256:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Template style overlay does not match the immutable plan.",
            details={"part": STYLES_PART},
        )
    styles = _style_map(package.xml(STYLES_PART), "output")
    missing = sorted(set(plan.imported + plan.replaced + plan.kept) - set(styles))
    if missing:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Template style overlay is missing a selected style after reopen.",
            details={"style_ids": missing},
        )
    return {"verified_style_ids": list(plan.requested)}


def _style_map(root: Element, label: str) -> dict[str, Element]:
    result: dict[str, Element] = {}
    for style in root.findall(qn("w", "style")):
        style_id = style.attrib.get(qn("w", "styleId"))
        style_type = style.attrib.get(qn("w", "type"))
        if not style_id or style_type not in _STYLE_TYPES or style_id in result:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "Word styles part contains an invalid or duplicate style.",
                details={"source": label, "style_id": style_id},
            )
        result[style_id] = style
    return result


def _validate_selected_style(
    style: Element,
    style_id: str,
    available: set[str],
) -> None:
    if next(style.iter(qn("w", "numId")), None) is not None:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Style overlay with numbering bindings requires graph-aware numbering merge.",
            status="enhancement_required",
            details={"style_id": style_id},
        )
    relationship_prefix = f"{{{NS['r']}}}"
    if any(
        name.startswith(relationship_prefix)
        for node in style.iter()
        for name in node.attrib
    ):
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Style overlay cannot import relationship-bound style content.",
            status="enhancement_required",
            details={"style_id": style_id},
        )
    dependencies = {
        value
        for name in _DEPENDENCY_ELEMENTS
        if (node := style.find(qn("w", name))) is not None
        if (value := node.attrib.get(qn("w", "val")))
    }
    missing = sorted(dependencies - available)
    if missing:
        _precondition_failed(
            "style-dependency-missing",
            style_id=style_id,
            dependencies=missing,
        )


def _precondition_failed(reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Template style overlay precondition did not match its immutable sources.",
        details={"reason": reason, **details},
    )
