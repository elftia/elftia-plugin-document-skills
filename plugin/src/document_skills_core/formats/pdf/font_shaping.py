"""Unicode fallback, UAX #9 run ordering, HarfBuzz shaping, and wrapping."""

from dataclasses import dataclass
import unicodedata
from typing import Any

from bidi.algorithm import (
    explicit_embed_and_overrides,
    get_base_level,
    get_embedding_levels,
    get_empty_storage,
    reorder_resolved_levels,
    resolve_implicit_levels,
    resolve_neutral_types,
    resolve_weak_types,
)
import uharfbuzz as hb

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .base14_metrics import base14_glyph_width
from .font_assets import FontAsset


@dataclass(frozen=True)
class ShapedGlyph:
    """One visually ordered glyph with logical extraction text."""

    font_id: str | None
    builtin_resource: str | None
    glyph_id: int | None
    text: str
    advance: float
    x_offset: float
    y_offset: float


@dataclass(frozen=True)
class ShapedLine:
    """A logical line and its visually ordered positioned glyphs."""

    text: str
    glyphs: tuple[ShapedGlyph, ...]
    width: float
    direction: str


@dataclass(frozen=True)
class _LogicalRun:
    level: int
    font_id: str | None
    chars: tuple[dict[str, Any], ...]
    visual_position: int


class TextShaper:
    """Shape text against the exact embedded faces registered by a request."""

    def __init__(self, assets: list[FontAsset]) -> None:
        self.assets = {asset.id: asset for asset in assets}
        self._hb_fonts = {
            asset.id: _harfbuzz_font(asset)
            for asset in assets
        }

    def require_coverage(self, text: str, style: dict[str, Any]) -> None:
        missing: list[dict[str, str]] = []
        seen: set[int] = set()
        for character in text:
            codepoint = ord(character)
            if character in "\r\n" or unicodedata.category(character).startswith("C"):
                continue
            if self._select_font(character, style) is not _MISSING:
                continue
            if codepoint in seen:
                continue
            seen.add(codepoint)
            missing.append({
                "character": character,
                "codepoint": f"U+{codepoint:04X}",
            })
        if missing:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "The requested font fallback chain does not cover every character.",
                status="enhancement_required",
                details={"missing_glyphs": missing},
            )

    def wrap_and_shape(
        self,
        text: str,
        style: dict[str, Any],
        max_width: float,
    ) -> list[ShapedLine]:
        """Greedily wrap logical text using shaped advances."""
        self.require_coverage(text, style)
        lines: list[ShapedLine] = []
        for source_line in text.split("\n"):
            words = source_line.split(" ")
            current = ""
            for word in words:
                candidate = word if not current else f"{current} {word}"
                shaped = self.shape_line(candidate, style)
                if shaped.width <= max_width:
                    current = candidate
                    continue
                if current:
                    lines.append(self.shape_line(current, style))
                broken, current = self._break_long_token(word, style, max_width)
                lines.extend(broken)
            lines.append(self.shape_line(current, style))
        return lines or [self.shape_line("", style)]

    def shape_line(self, text: str, style: dict[str, Any]) -> ShapedLine:
        if not text:
            direction = _base_direction(text, style["direction"])
            return ShapedLine(text="", glyphs=(), width=0.0, direction=direction)
        runs, direction = self._logical_runs(text, style)
        glyphs: list[ShapedGlyph] = []
        for run in sorted(runs, key=lambda item: item.visual_position):
            run_text = "".join(character["ch"] for character in run.chars)
            if run.font_id is None:
                glyphs.extend(_shape_builtin_run(run_text, run.level, style))
            else:
                glyphs.extend(
                    self._shape_embedded_run(
                        run.font_id,
                        run_text,
                        run.level,
                        style,
                    )
                )
        return ShapedLine(
            text=text,
            glyphs=tuple(glyphs),
            width=sum(glyph.advance for glyph in glyphs),
            direction=direction,
        )

    def _break_long_token(
        self,
        token: str,
        style: dict[str, Any],
        max_width: float,
    ) -> tuple[list[ShapedLine], str]:
        completed: list[ShapedLine] = []
        current = ""
        for cluster in _logical_clusters(token):
            candidate = current + cluster
            if self.shape_line(candidate, style).width <= max_width:
                current = candidate
                continue
            if not current:
                raise DocumentSkillsError(
                    ErrorCode.REQUEST_INVALID,
                    "A shaped text cluster exceeds the available content width.",
                    status="invalid_request",
                    details={"max_width": round(max_width, 4)},
                )
            completed.append(self.shape_line(current, style))
            current = cluster
        return completed, current

    def _logical_runs(
        self,
        text: str,
        style: dict[str, Any],
    ) -> tuple[list[_LogicalRun], str]:
        base_level = _base_level(text, style["direction"])
        storage = get_empty_storage()
        storage["base_level"] = base_level
        storage["base_dir"] = "R" if base_level else "L"
        get_embedding_levels(text, storage, False, False)
        for index, character in enumerate(storage["chars"]):
            character["index"] = index
        explicit_embed_and_overrides(storage, False)
        resolve_weak_types(storage, False)
        resolve_neutral_types(storage, False)
        resolve_implicit_levels(storage, False)

        logical_chars = storage["chars"]
        for character in logical_chars:
            selected = self._select_font(character["ch"], style)
            if selected is _MISSING:
                raise AssertionError("coverage must be checked before shaping")
            character["font_id"] = selected

        visual_storage = {
            "base_level": base_level,
            "base_dir": storage["base_dir"],
            "chars": [dict(character) for character in logical_chars],
            "runs": [],
        }
        reorder_resolved_levels(visual_storage, False)
        visual_positions = {
            character["index"]: index
            for index, character in enumerate(visual_storage["chars"])
        }

        runs: list[_LogicalRun] = []
        current: list[dict[str, Any]] = []
        current_key: tuple[int, str | None] | None = None
        for character in logical_chars:
            key = (int(character["level"]), character["font_id"])
            if current and key != current_key:
                runs.append(_make_run(current, current_key, visual_positions))
                current = []
            current.append(character)
            current_key = key
        if current:
            runs.append(_make_run(current, current_key, visual_positions))
        return runs, "rtl" if base_level else "ltr"

    def _select_font(self, character: str, style: dict[str, Any]) -> object:
        family = style["font_family"]
        candidates: list[str | None] = []
        if family == "Helvetica":
            candidates.append(None)
        else:
            candidates.append(family)
        candidates.extend(style.get("fallback_fonts", []))
        for candidate in candidates:
            if candidate is None:
                try:
                    character.encode("latin-1", errors="strict")
                    return None
                except UnicodeEncodeError:
                    continue
            asset = self.assets.get(candidate)
            if asset is not None and ord(character) in asset.cmap:
                return candidate
        return _MISSING

    def _shape_embedded_run(
        self,
        font_id: str,
        text: str,
        level: int,
        style: dict[str, Any],
    ) -> list[ShapedGlyph]:
        asset = self.assets[font_id]
        buffer = hb.Buffer()
        buffer.add_codepoints([ord(character) for character in text])
        buffer.guess_segment_properties()
        buffer.direction = "rtl" if level % 2 else "ltr"
        if style.get("language"):
            buffer.language = style["language"]
        hb.shape(self._hb_fonts[font_id], buffer)
        cluster_text = _cluster_text_map(text, buffer.glyph_infos)
        scale = style["font_size"] / asset.units_per_em
        seen_clusters: set[int] = set()
        glyphs: list[ShapedGlyph] = []
        for info, position in zip(buffer.glyph_infos, buffer.glyph_positions, strict=True):
            if info.codepoint == 0:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "HarfBuzz produced a missing glyph for a covered codepoint.",
                    details={"font_id": font_id, "cluster": info.cluster},
                )
            extraction_text = cluster_text[info.cluster]
            if info.cluster in seen_clusters:
                extraction_text = "\u200b"
            seen_clusters.add(info.cluster)
            glyphs.append(ShapedGlyph(
                font_id=font_id,
                builtin_resource=None,
                glyph_id=info.codepoint,
                text=extraction_text,
                advance=position.x_advance * scale,
                x_offset=position.x_offset * scale,
                y_offset=position.y_offset * scale,
            ))
        return glyphs


_MISSING = object()


def resolved_style(block_type: str, style: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve the public style defaults for shaping and emission."""
    if style is not None:
        return style
    size = 16.0 if block_type == "heading" else 12.0
    return {
        "font_family": "Helvetica",
        "font_size": size,
        "font_weight": "bold" if block_type == "heading" else "normal",
        "font_style": "normal",
        "color": [0.0, 0.0, 0.0],
        "line_height": 28.0 if block_type == "heading" else 14.0,
        "alignment": "left",
        "fallback_fonts": [],
        "direction": "auto",
        "language": None,
    }


def _make_run(
    chars: list[dict[str, Any]],
    key: tuple[int, str | None] | None,
    visual_positions: dict[int, int],
) -> _LogicalRun:
    assert key is not None
    return _LogicalRun(
        level=key[0],
        font_id=key[1],
        chars=tuple(chars),
        visual_position=min(visual_positions[character["index"]] for character in chars),
    )


def _harfbuzz_font(asset: FontAsset) -> hb.Font:
    face = hb.Face(asset.data)
    font = hb.Font(face)
    hb.ot_font_set_funcs(font)
    font.scale = (asset.units_per_em, asset.units_per_em)
    return font


def _shape_builtin_run(
    text: str,
    level: int,
    style: dict[str, Any],
) -> list[ShapedGlyph]:
    resource = {
        ("normal", "normal"): "F1",
        ("bold", "normal"): "F2",
        ("normal", "italic"): "F3",
        ("bold", "italic"): "F4",
    }[(style["font_weight"], style["font_style"])]
    characters = reversed(text) if level % 2 else text
    return [
        ShapedGlyph(
            font_id=None,
            builtin_resource=resource,
            glyph_id=None,
            text=character,
            advance=base14_glyph_width(character, style["font_size"], resource),
            x_offset=0.0,
            y_offset=0.0,
        )
        for character in characters
    ]


def _cluster_text_map(text: str, infos: list[hb.GlyphInfo]) -> dict[int, str]:
    clusters = sorted({int(info.cluster) for info in infos})
    mapping: dict[int, str] = {}
    for index, cluster in enumerate(clusters):
        end = clusters[index + 1] if index + 1 < len(clusters) else len(text)
        mapping[cluster] = text[cluster:end]
    return mapping


def _logical_clusters(text: str) -> list[str]:
    """Keep combining sequences and emoji joiners intact when wrapping."""
    clusters: list[str] = []
    current = ""
    join_next = False
    for character in text:
        codepoint = ord(character)
        extends = (
            join_next
            or character == "\u200d"
            or unicodedata.combining(character) != 0
            or unicodedata.category(character) in {"Mc", "Me"}
            or 0xFE00 <= codepoint <= 0xFE0F
            or 0x1F3FB <= codepoint <= 0x1F3FF
        )
        if current and not extends:
            clusters.append(current)
            current = character
        else:
            current += character
        join_next = character == "\u200d"
    if current:
        clusters.append(current)
    return clusters


def _base_level(text: str, direction: str) -> int:
    if direction == "ltr":
        return 0
    if direction == "rtl":
        return 1
    return int(get_base_level(text))


def _base_direction(text: str, direction: str) -> str:
    return "rtl" if _base_level(text, direction) else "ltr"
