"""Source-baselined watermark expectations derived from public requests."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any

from .create_images import image_placement
from .image_assets import ImageAsset, load_image_asset
from .watermark_expected_content import expected_content_bytes
from .watermark_fonts import canonical_font_record_matches
from .watermark_layout import (
    image_box_origin,
    image_matrix,
    transformed_unit_bbox,
    watermark_rotation,
)
from .watermark_resource_scan import (
    FontResource,
    page_font_map,
    page_resource_names,
)
from .watermark_scan import scan_watermark_uses


_MAX_RESOURCE_CANDIDATES = 4_096
_MAX_FONT_CANDIDATES = 10_000


@dataclass(frozen=True)
class ExpectedWatermark:
    """One request-derived watermark use on one output page."""

    primitive_index: int
    primitive_pages: tuple[int, ...]
    page: int
    kind: str
    graphics_state: str
    opacity: float
    content_stream: bytes
    content_stream_sha256: str
    content_length: int
    source_objects: frozenset[int]
    text: str | None
    font_resource: str | None
    base_font: str | None
    font_source_dictionary_sha256: str | None
    font_source_keys: tuple[str, ...] | None
    font_must_be_added: bool
    size: float | None
    color: tuple[float, ...] | None
    rotation: float
    position: str | tuple[float, float]
    image_resource: str | None
    image_asset: ImageAsset | None
    image_alt: str | None
    bbox: tuple[float, float, float, float] | None


@dataclass
class PageWatermarkState:
    """Baseline uses and staged resource occupancy for one logical page."""

    graphics_names: set[str]
    image_names: set[str]
    fonts: dict[str, FontResource | PlannedFont | None]
    source_objects: frozenset[int]
    baseline: list[tuple[Any, ...]]
    expected: list[ExpectedWatermark] = field(default_factory=list)


@dataclass(frozen=True)
class PlannedFont:
    """A simulated font allocation owned by an earlier/current primitive."""

    base_font: str
    primitive_index: int


def new_page_watermark_state(model: Any, page: Any) -> PageWatermarkState:
    """Snapshot source watermark semantics and occupied resource names."""
    return PageWatermarkState(
        graphics_names=page_resource_names(model, page, "/ExtGState"),
        image_names=page_resource_names(model, page, "/XObject"),
        fonts=page_font_map(model, page),
        source_objects=frozenset(model.objects),
        baseline=[
            use.semantic_fingerprint() for use in scan_watermark_uses(model, page)
        ],
    )


def plan_watermark_expectation(
    pages: list[Any],
    primitive: dict[str, Any],
    primitive_index: int,
    source_objects: frozenset[int] | None,
) -> None:
    """Plan collision-free names and exact image semantics from the request."""
    selected = [(number, pages[number - 1]) for number in primitive["pages"]]
    states = [_state(page) for _number, page in selected]
    if source_objects is not None:
        # Identity-replacing stages may reuse old object numbers. Refresh only
        # ownership; request-derived baseline semantics remain independently checked.
        for state in states:
            state.source_objects = source_objects
    graphics_state = _plan_name(
        [state.graphics_names for state in states],
        "DSWMGS",
    )
    image_request = primitive.get("image")
    image_resource = None
    image_asset = None
    font_resource = None
    base_font = None
    if image_request is not None:
        image_resource = _plan_name(
            [state.image_names for state in states],
            "DSWMImage",
        )
        image_asset = load_image_asset(image_request)
    else:
        base_font = primitive.get("font", "Helvetica")
        font_resource = _plan_font(states, base_font, primitive_index)
    for number, page in selected:
        state = _state(page)
        font = (
            state.fonts.get(f"/{font_resource}")
            if font_resource is not None
            else None
        )
        position = primitive.get("position", "center")
        expected_position = (
            (float(position["x"]), float(position["y"]))
            if isinstance(position, dict)
            else position
        )
        expected_graphics = f"/{graphics_state}"
        expected_font = f"/{font_resource}" if font_resource is not None else None
        expected_image = f"/{image_resource}" if image_resource is not None else None
        content = expected_content_bytes(
            page,
            primitive,
            asset=image_asset,
            graphics_state=expected_graphics,
            font_resource=expected_font,
            image_resource=expected_image,
        )
        _state(page).expected.append(ExpectedWatermark(
            primitive_index=primitive_index,
            primitive_pages=tuple(sorted(set(primitive["pages"]))),
            page=number,
            kind="image" if image_asset is not None else "text",
            graphics_state=expected_graphics,
            opacity=float(primitive["opacity"]),
            content_stream=content,
            content_stream_sha256=hashlib.sha256(content).hexdigest(),
            content_length=len(content),
            source_objects=state.source_objects,
            text=primitive.get("text"),
            font_resource=expected_font,
            base_font=base_font,
            font_source_dictionary_sha256=(
                font.dictionary_sha256
                if isinstance(font, FontResource)
                else None
            ),
            font_source_keys=(font.keys if isinstance(font, FontResource) else None),
            font_must_be_added=(
                isinstance(font, PlannedFont)
                and font.primitive_index == primitive_index
            ),
            size=(
                float(primitive.get("size", 48.0))
                if image_asset is None
                else None
            ),
            color=(
                tuple(float(value) for value in primitive.get(
                    "color",
                    [0.7, 0.7, 0.7],
                ))
                if image_asset is None
                else None
            ),
            rotation=float(watermark_rotation(primitive, image_asset is not None)),
            position=expected_position,
            image_resource=expected_image,
            image_asset=image_asset,
            image_alt=(
                image_request.get("alt")
                if image_request is not None and image_request.get("alt")
                else None
            ),
            bbox=(
                _image_bbox(page, primitive, image_asset)
                if image_asset is not None
                else None
            ),
        ))


def _plan_name(
    resource_sets: list[set[str]],
    prefix: str,
) -> str:
    occupied = set().union(*resource_sets)
    for index in range(_MAX_RESOURCE_CANDIDATES):
        name = prefix if index == 0 else f"{prefix}{index}"
        resource = f"/{name}"
        if resource in occupied:
            continue
        for resources in resource_sets:
            resources.add(resource)
        return name
    raise ValueError("Watermark resource planning exceeded its closed bound.")


def _plan_font(
    states: list[PageWatermarkState],
    base_font: str,
    primitive_index: int,
) -> str:
    for index in range(_MAX_FONT_CANDIDATES):
        name = "DSWMFont" if index == 0 else f"DSWMFont{index}"
        resource = f"/{name}"
        entries = [state.fonts.get(resource) for state in states]
        if entries and all(
            (isinstance(entry, PlannedFont) and entry.base_font == base_font)
            or (
                isinstance(entry, FontResource)
                and canonical_font_record_matches(entry, base_font)
            )
            for entry in entries
        ):
            return name
        if any(resource in state.fonts for state in states):
            continue
        for state in states:
            state.fonts[resource] = PlannedFont(base_font, primitive_index)
        return name
    raise ValueError("Watermark font planning exceeded its closed bound.")


def _image_bbox(
    page: Any,
    primitive: dict[str, Any],
    asset: ImageAsset,
) -> tuple[float, float, float, float]:
    image = primitive["image"]
    box_left, box_bottom = image_box_origin(
        page,
        primitive.get("position", "center"),
        width=image["width"],
        height=image["height"],
    )
    placement = image_placement(
        image,
        asset,
        left=box_left,
        top=box_bottom + image["height"],
    )
    rotation = watermark_rotation(primitive, True)
    return (
        placement["visible_bbox"]
        if rotation == 0.0
        else transformed_unit_bbox(image_matrix(placement["draw"], rotation))
    )


def _state(page: Any) -> PageWatermarkState:
    state = page.watermark_state
    if not isinstance(state, PageWatermarkState):
        raise ValueError("Page watermark expectation state is missing.")
    return state
