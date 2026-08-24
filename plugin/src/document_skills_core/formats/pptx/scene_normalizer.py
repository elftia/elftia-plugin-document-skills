"""Deterministic classification and duplicate-suppression for private scenes."""

from collections import Counter
from dataclasses import dataclass
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .scene import SCENE_LIMITS, SceneDeck

_NATIVE_KINDS = {"rectangle", "rounded-rectangle", "ellipse", "line", "text", "image"}
_SAMPLE_LIMIT = 32


@dataclass(frozen=True)
class NormalizedScene:
    slides: tuple[tuple[dict[str, Any], ...], ...]
    assets: dict[str, dict[str, Any]]
    diagnostics: dict[str, Any]
    visual_sources: tuple[dict[str, Any], ...] = ()
    slide_fills: tuple[str, ...] = ()


def normalize_scene(deck: SceneDeck) -> NormalizedScene:
    normalized_slides: list[tuple[dict[str, Any], ...]] = []
    slide_fills: list[str] = []
    outcomes: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    unknown_hints: Counter[str] = Counter()
    fidelity = {
        outcome: {"count": 0, "area": 0.0, "reasons": Counter(), "samples": []}
        for outcome in ("native", "approximated", "rasterized")
    }
    unsupported_css: Counter[str] = Counter()
    unsupported_samples: list[dict[str, str]] = []
    unsupported_total = 0
    font_samples: list[dict[str, Any]] = []
    font_total = 0
    font_substitutions = 0
    font_capture_truncated = 0
    suppressed = 0
    for slide in deck.slides:
        slide_fills.append(slide["root_fill"])
        emitted: list[dict[str, Any]] = []
        suppressed_roots = {
            item["source_id"]
            for item in slide["items"]
            if item["ignored"] or item["capture_outcome"] == "rasterized"
        }
        for item in slide["items"]:
            if item["ignored"]:
                outcomes["rejected"] += 1
                reasons["ignored_by_hint"] += 1
                continue
            if _has_ancestor(item, suppressed_roots):
                suppressed += 1
                continue
            outcome, reason = _classify(item)
            if outcome == "rejected":
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "HTML scene contains an item that cannot be emitted safely.",
                    details={"source_id": item["source_id"], "reason": reason},
                )
            record = {**item, "outcome": outcome, "outcome_reason": reason}
            paint_records = _paint_records(record)
            emitted.extend(paint_records)
            outcomes[outcome] += 1
            kinds[item["kind"]] += 1
            fidelity_record = fidelity[outcome]
            fidelity_record["count"] += 1
            area = item["width"] * item["height"]
            fidelity_record["area"] += area
            if reason:
                fidelity_record["reasons"][reason] += 1
            if len(fidelity_record["samples"]) < _SAMPLE_LIMIT:
                fidelity_record["samples"].append(
                    _fidelity_sample(item, reason, area)
                )
            if reason:
                reasons[reason] += 1
            for unsupported in item["unsupported"]:
                unsupported_css[unsupported] += 1
                unsupported_total += 1
                if len(unsupported_samples) < _SAMPLE_LIMIT:
                    unsupported_samples.append({
                        "source_id": item["source_id"],
                        "reason": unsupported,
                    })
            for hint in item["unknown_hints"]:
                unknown_hints[hint] += 1
            if item["text"]:
                font_total += 1
                evidence = item["font_evidence"]
                font_substitutions += evidence["substitution"] is not None
                font_capture_truncated += evidence["truncated"] is True
                if len(font_samples) < _SAMPLE_LIMIT:
                    font_samples.append({
                        "source_id": item["source_id"],
                        "requested": evidence["requested_families"],
                        "computed": evidence["computed_family"],
                        "platform_fonts": evidence["platform_fonts"],
                        "substitution": evidence["substitution"],
                        "capture_truncated": evidence["truncated"],
                    })
            for extra in paint_records:
                if extra["source_id"] == record["source_id"]:
                    continue
                outcomes["native"] += 1
                kinds[extra["kind"]] += 1
                extra_area = extra["width"] * extra["height"]
                fidelity["native"]["count"] += 1
                fidelity["native"]["area"] += extra_area
                if len(fidelity["native"]["samples"]) < _SAMPLE_LIMIT:
                    fidelity["native"]["samples"].append(
                        _fidelity_sample(extra, None, extra_area)
                    )
        emitted.sort(key=lambda entry: (entry["paint_order"], entry["dom_index"], entry["source_id"]))
        normalized_slides.append(tuple(emitted))
    observed_limits = {**deck.observed, "scene_bytes": deck.scene_bytes}
    return NormalizedScene(
        slides=tuple(normalized_slides),
        assets=deck.assets,
        diagnostics={
            "outcomes": dict(sorted(outcomes.items())),
            "kinds": dict(sorted(kinds.items())),
            "reasons": dict(sorted(reasons.items())),
            "fidelity": {
                outcome: _fidelity_diagnostics(record)
                for outcome, record in fidelity.items()
            },
            "unsupported_css": {
                "total": unsupported_total,
                "by_reason": dict(sorted(unsupported_css.items())),
                "samples": unsupported_samples,
                "truncated": max(0, unsupported_total - len(unsupported_samples)),
            },
            "unknown_hints": _bounded_counter(unknown_hints),
            "blocked_resources": {
                "total": deck.blocked_resources["total"],
                "by_reason": dict(deck.blocked_resources["by_reason"]),
                "samples": [dict(sample) for sample in deck.blocked_resources["samples"]],
                "truncated": deck.blocked_resources["truncated"],
            },
            "font_evidence": {
                "total": font_total,
                "substitutions": font_substitutions,
                "samples": font_samples,
                "truncated": max(0, font_total - len(font_samples)),
                "capture_truncated": font_capture_truncated,
            },
            "duplicate_descendants_suppressed": suppressed,
            "limits": {
                "observed": observed_limits,
                "ceilings": dict(SCENE_LIMITS),
                "utilization": {
                    name: observed_limits[name] / ceiling
                    for name, ceiling in SCENE_LIMITS.items()
                    if name in observed_limits
                },
            },
        },
        visual_sources=deck.visual_sources,
        slide_fills=tuple(slide_fills),
    )


def _classify(item: dict[str, Any]) -> tuple[str, str | None]:
    if item["capture_outcome"] == "rejected":
        return "rejected", item["reason"] or "capture_rejected"
    if item["capture_outcome"] == "rasterized":
        if item["asset_id"] is None:
            return "rejected", "raster_asset_missing"
        return "rasterized", item["reason"] or "unsupported_css"
    if item["unsupported"]:
        return "rejected", item["unsupported"][0]
    if item["kind"] not in _NATIVE_KINDS:
        return "rejected", "unsupported_kind"
    if item["kind"] == "image" and item["asset_id"] is None:
        return "rejected", "image_asset_missing"
    if item["approximations"]:
        return "approximated", item["approximations"][0]
    return "native", None


def _has_ancestor(
    item: dict[str, Any],
    rasterized: set[str],
) -> bool:
    return any(parent in rasterized for parent in item["dom_ancestor_ids"])


def _paint_records(parent: dict[str, Any]) -> list[dict[str, Any]]:
    pseudos = [
        pseudo
        for pseudo in parent["pseudo"]
        if pseudo.get("simple") and pseudo.get("content")
    ] if parent["outcome"] != "rasterized" else []
    if not pseudos:
        return [parent]
    before = [_pseudo_item(parent, pseudo) for pseudo in pseudos if pseudo["paint_slot"] == 2]
    after = [_pseudo_item(parent, pseudo) for pseudo in pseudos if pseudo["paint_slot"] == 4]
    has_box = parent["kind"] != "text" or parent["border_width"] > 0 or _visible_fill(parent["fill"])
    records: list[dict[str, Any]] = []
    if has_box:
        records.append({**parent, "text": "", "paragraphs": []})
    records.extend(before)
    if parent["text"]:
        content_id = parent["source_id"] if not has_box else f"{parent['source_id'][:72]}:content"
        records.append({
            **parent,
            "source_id": content_id,
            "parent_source_id": parent["source_id"] if has_box else parent["parent_source_id"],
            "kind": "text",
            "fill": "rgba(0, 0, 0, 0)",
            "border_width": 0,
            "radius": 0,
            "paint_order": parent["paint_order"] + 2,
            "pseudo": [],
        })
    records.extend(after)
    return records


def _pseudo_item(parent: dict[str, Any], pseudo: dict[str, Any]) -> dict[str, Any]:
    style = {
        "font_family": pseudo.get("font_family"),
        "font_size": pseudo.get("font_size"),
        "font_weight": pseudo.get("font_weight"),
        "font_style": pseudo.get("font_style"),
        "text_decoration": pseudo.get("text_decoration"),
        "color": pseudo.get("color"),
        "text_align": pseudo.get("text_align", "left"),
        "line_height": pseudo.get("line_height", "normal"),
        "letter_spacing": pseudo.get("letter_spacing", "normal"),
    }
    return {
        **parent,
        "source_id": pseudo["source_id"],
        "parent_source_id": parent["source_id"],
        "kind": "text",
        "x": pseudo["x"],
        "y": pseudo["y"],
        "width": pseudo["width"],
        "height": pseudo["height"],
        "rotation": 0,
        "opacity": pseudo["opacity"],
        "paint_order": pseudo["paint_order"],
        "text": pseudo["content"],
        "text_style": style,
        "paragraphs": [{
            "runs": [{"text": pseudo["content"], "style": style}],
            "alignment": style["text_align"],
            "line_height": style["line_height"],
        }],
        "text_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        "fill": "rgba(0, 0, 0, 0)",
        "border_width": 0,
        "asset_id": None,
        "pseudo": [],
        "outcome": "native",
        "outcome_reason": None,
    }


def _visible_fill(value: str) -> bool:
    if value in {"transparent", "rgba(0, 0, 0, 0)"}:
        return False
    if value.startswith("rgba("):
        try:
            return float(value.removesuffix(")").split(",")[-1]) > 0
        except ValueError:
            return True
    return True


def _bounded_counter(values: Counter[str]) -> dict[str, Any]:
    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    samples = [{"reason": reason, "count": count} for reason, count in ordered[:_SAMPLE_LIMIT]]
    return {
        "total": sum(values.values()),
        "samples": samples,
        "truncated": max(0, len(ordered) - len(samples)),
    }


def _fidelity_diagnostics(record: dict[str, Any]) -> dict[str, Any]:
    count = record["count"]
    samples = record["samples"]
    return {
        "count": count,
        "area": record["area"],
        "by_reason": dict(sorted(record["reasons"].items())),
        "samples": samples,
        "truncated": max(0, count - len(samples)),
    }


def _fidelity_sample(
    item: dict[str, Any],
    reason: str | None,
    area: float,
) -> dict[str, Any]:
    source_id = item["source_id"]
    return {
        "source_id": source_id,
        "element_selector": f'[data-elftia-source-id="{source_id}"]',
        "reason": reason,
        "area": area,
        "bbox": {
            "x": item["x"],
            "y": item["y"],
            "width": item["width"],
            "height": item["height"],
        },
        "asset_sha256": item.get("asset_id"),
    }
