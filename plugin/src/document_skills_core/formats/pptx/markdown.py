"""Bounded Markdown-to-typed-deck semantic reconstruction."""

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_RUNS_PER_TEXT_FRAME, MAX_SLIDES
from .content_contracts import parse_slide_metadata
from .markdown_values import (
    _bounded_text,
    _is_table_start,
    _parse_table,
    _resolve_image,
    _visible_text,
)

MAX_MARKDOWN_BYTES = 1 * 1024 * 1024
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST = re.compile(r"^\s*(?:(?P<unordered>[-+*])|(?P<number>\d+)[.)])\s+(?P<text>.+?)\s*$")
_IMAGE = re.compile(
    r"^\s*!\[(?P<alt>[^\]]*)\]\(\s*(?P<target><[^>]+>|[^)\s]+)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)\s*$"
)
_METADATA = re.compile(r"^\s*<!--\s*pptx:\s*(?P<json>\{.*\})\s*-->\s*$")


def parse_markdown_deck(
    path: Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse the supported Markdown subset into the existing typed deck model."""

    if not path.is_file():
        _invalid("The Markdown source must be an existing local file.", path=str(path))
    payload = path.read_bytes()
    if not payload or len(payload) > MAX_MARKDOWN_BYTES:
        _invalid(
            "The Markdown source exceeds the byte limit or is empty.",
            bytes=len(payload),
            ceiling=MAX_MARKDOWN_BYTES,
        )
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        _invalid("The Markdown source must be strict UTF-8.", offset=error.start)

    slides, mappings = _parse_lines(text.splitlines(), path.parent.resolve())
    if not slides:
        _invalid("Markdown must contain presentation content.")
    metadata = dict(arguments["metadata"])
    if not metadata["title"]:
        metadata["title"] = slides[0]["title"] or path.stem
    if not metadata["subject"]:
        metadata["subject"] = "Semantic reconstruction from Markdown"
    deck = {
        "layout_tokens": arguments["layout_tokens"],
        "metadata": metadata,
        "slides": slides,
        "theme": arguments["theme"],
    }
    evidence = {
        "source_sha256": sha256(payload).hexdigest(),
        "source_bytes": len(payload),
        "semantic_reconstruction": True,
        "visual_preservation_claimed": False,
        "slides": mappings,
    }
    return deck, evidence


def _parse_lines(
    lines: list[str],
    source_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    slides: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    pending_metadata: dict[str, Any] | None = None
    index = 0

    def ensure_slide(line_number: int) -> dict[str, Any]:
        nonlocal current, pending_metadata
        if current is None:
            current = _new_slide("Untitled", 2, line_number, pending_metadata)
            pending_metadata = None
        return current

    def finish_slide(end_line: int) -> None:
        nonlocal current
        if current is None:
            return
        if len(slides) >= MAX_SLIDES:
            _invalid("Markdown contains too many slides.", ceiling=MAX_SLIDES)
        slide, mapping = _finalize_slide(current, len(slides) + 1, end_line)
        slides.append(slide)
        mappings.append(mapping)
        current = None

    while index < len(lines):
        line = lines[index]
        line_number = index + 1
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        metadata_match = _METADATA.fullmatch(line)
        if metadata_match:
            metadata = _decode_metadata(metadata_match.group("json"), line_number)
            if current is None:
                if pending_metadata is not None:
                    _invalid("Only one metadata object is allowed per slide.", line=line_number)
                pending_metadata = metadata
            else:
                if current["metadata_seen"]:
                    _invalid("Only one metadata object is allowed per slide.", line=line_number)
                current["metadata"] = metadata
                current["metadata_seen"] = True
            index += 1
            continue
        if "<!--" in line and "pptx:" in line:
            _invalid("PPTX metadata comments must be single-line JSON comments.", line=line_number)

        heading = _HEADING.fullmatch(line)
        if heading:
            level = len(heading.group(1))
            if level > 3:
                _invalid("Only H1, H2, and H3 headings are supported.", line=line_number)
            finish_slide(line_number - 1)
            current = _new_slide(
                _visible_text(heading.group(2)),
                level,
                line_number,
                pending_metadata,
            )
            pending_metadata = None
            index += 1
            continue

        if stripped == ":::notes":
            slide = ensure_slide(line_number)
            if slide["notes"] is not None:
                _invalid("Only one notes block is allowed per slide.", line=line_number)
            notes: list[str] = []
            index += 1
            while index < len(lines) and lines[index].strip() != ":::":
                notes.append(lines[index])
                index += 1
            if index >= len(lines):
                _invalid("Markdown notes block is not closed.", line=line_number)
            slide["notes"] = _bounded_text("\n".join(notes).strip(), "notes", line_number)
            slide["end_line"] = index + 1
            index += 1
            continue

        if stripped.startswith(("```", "~~~")):
            slide = ensure_slide(line_number)
            marker = stripped[:3]
            language = stripped[3:].strip()
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(marker):
                code.append(lines[index])
                index += 1
            if index >= len(lines):
                _invalid("Markdown code fence is not closed.", line=line_number)
            rendered = "\n".join(code)
            if language:
                rendered = f"[{language}]\n{rendered}"
            _add_text(slide, _bounded_text(rendered, "code", line_number), "code", line_number)
            slide["end_line"] = index + 1
            index += 1
            continue

        image = _IMAGE.fullmatch(line)
        if image:
            slide = ensure_slide(line_number)
            if slide["image_reference"] is not None:
                _invalid("Only one image is supported per Markdown slide.", line=line_number)
            asset = _resolve_image(source_root, image.group("target"), line_number)
            slide["image_reference"] = {
                "path": str(asset),
                "fit": "contain",
                "alt_text": _bounded_text(
                    _visible_text(image.group("alt")) or "Markdown image",
                    "image.alt",
                    line_number,
                ),
            }
            slide["image_line"] = line_number
            slide["end_line"] = line_number
            index += 1
            continue
        if "![" in line:
            _invalid("Markdown images must occupy their own line.", line=line_number)

        if index + 1 < len(lines) and _is_table_start(line, lines[index + 1]):
            slide = ensure_slide(line_number)
            if slide["table"] is not None:
                _invalid("Only one table is supported per Markdown slide.", line=line_number)
            table, next_index = _parse_table(lines, index)
            slide["table"] = table
            slide["table_line"] = line_number
            slide["end_line"] = next_index
            index = next_index
            continue

        list_match = _LIST.fullmatch(line)
        if list_match:
            slide = ensure_slide(line_number)
            prefix = "•" if list_match.group("unordered") else f"{list_match.group('number')}."
            _add_text(
                slide,
                f"{prefix} {_visible_text(list_match.group('text'))}",
                "list",
                line_number,
            )
            index += 1
            continue

        if stripped.startswith("#"):
            _invalid("Malformed or unsupported Markdown heading.", line=line_number)
        slide = ensure_slide(line_number)
        paragraph = [stripped]
        index += 1
        while index < len(lines) and lines[index].strip():
            candidate = lines[index]
            if _starts_special(lines, index):
                break
            if "![" in candidate:
                _invalid("Markdown images must occupy their own line.", line=index + 1)
            paragraph.append(candidate.strip())
            index += 1
        _add_text(
            slide,
            _visible_text(" ".join(paragraph)),
            "paragraph",
            line_number,
        )

    finish_slide(len(lines))
    if pending_metadata is not None:
        _invalid("Slide metadata is not followed by slide content.", line=len(lines))
    return slides, mappings


def _new_slide(
    title: str,
    heading_level: int,
    line: int,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "title": _bounded_text(title, "heading", line),
        "heading_level": heading_level,
        "start_line": line,
        "end_line": line,
        "text_blocks": [],
        "table": None,
        "table_line": None,
        "image_reference": None,
        "image_line": None,
        "notes": None,
        "metadata": metadata or {"notes": None, "recipe": None, "tags": []},
        "metadata_seen": metadata is not None,
    }


def _finalize_slide(
    source: dict[str, Any],
    number: int,
    end_line: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = source["metadata"]
    notes = source["notes"]
    if metadata["notes"] is not None:
        if notes is not None and notes != metadata["notes"]:
            _invalid("Slide notes conflict with metadata notes.", line=source["start_line"])
        notes = metadata["notes"]
    default_recipe = {1: "cover", 2: "content", 3: "section"}[source["heading_level"]]
    recipe = metadata["recipe"] or default_recipe
    runs = []
    for item in source["text_blocks"]:
        style = {"font": "Consolas", "font_size": 12.0} if item["kind"] == "code" else None
        runs.append({"text": item["text"], "style": style})
    shapes = []
    if runs:
        shapes.append({
            "text": "\n".join(item["text"] for item in source["text_blocks"]),
            "runs": runs,
        })
    slide = {
        "layout": "title" if source["heading_level"] == 1 else "content",
        "recipe": recipe,
        "title": source["title"],
        "shapes": shapes,
        "table": source["table"],
        "chart_reference": None,
        "image_reference": source["image_reference"],
        "notes": notes,
    }
    mapping = {
        "slide": number,
        "heading_level": source["heading_level"],
        "source_lines": {"start": source["start_line"], "end": max(end_line, source["end_line"])},
        "recipe": recipe,
        "tags": metadata["tags"],
        "native_objects": {
            "image": source["image_reference"] is not None,
            "table": source["table"] is not None,
            "text_blocks": len(source["text_blocks"]),
        },
    }
    return slide, mapping


def _add_text(slide: dict[str, Any], text: str, kind: str, line: int) -> None:
    text = _bounded_text(text, kind, line)
    if not text:
        return
    if len(slide["text_blocks"]) >= MAX_RUNS_PER_TEXT_FRAME:
        _invalid("Markdown slide contains too many text blocks.", line=line)
    slide["text_blocks"].append({"kind": kind, "line": line, "text": text})
    slide["end_line"] = line


def _decode_metadata(payload: str, line: int) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        _invalid("Markdown slide metadata is not valid JSON.", line=line, column=error.colno)
    return parse_slide_metadata(value, line)


def _starts_special(lines: list[str], index: int) -> bool:
    line = lines[index]
    stripped = line.strip()
    return bool(
        _HEADING.fullmatch(line)
        or _LIST.fullmatch(line)
        or _IMAGE.fullmatch(line)
        or _METADATA.fullmatch(line)
        or stripped in {":::notes"}
        or stripped.startswith(("```", "~~~"))
        or (index + 1 < len(lines) and _is_table_start(line, lines[index + 1]))
    )


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
