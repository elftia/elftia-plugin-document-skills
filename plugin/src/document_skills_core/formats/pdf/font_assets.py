"""Bounded, hash-bound TrueType loading and deterministic subsetting."""

from dataclasses import dataclass
from io import BytesIO
import hashlib
from pathlib import Path
import stat
from typing import Any, Iterable

from fontTools import subset
from fontTools.ttLib import TTFont, TTLibError
from fontTools.varLib.instancer import instantiateVariableFont

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

MAX_FONT_BYTES = 32 * 1024 * 1024
MAX_FONT_GLYPHS = 65_535
_ALLOWED_SFNT_MAGIC = {b"\x00\x01\x00\x00", b"true"}
_FORBIDDEN_EMBEDDING_BITS = 0x0002 | 0x0100 | 0x0200


@dataclass(frozen=True)
class FontAsset:
    """A validated, instantiated, subset TrueType face."""

    id: str
    path: Path
    source_sha256: str
    subset_sha256: str
    data: bytes
    cmap: dict[int, str]
    postscript_name: str
    license: str
    units_per_em: int
    ascent: int
    descent: int
    cap_height: int
    bbox: tuple[int, int, int, int]
    italic_angle: float
    glyph_count: int


def load_font_assets(
    specs: list[dict[str, str]],
    document_text: Iterable[str],
) -> list[FontAsset]:
    """Load every declared face and subset it to document codepoints."""
    codepoints = {
        ord(character)
        for text in document_text
        for character in text
        if character not in "\r\n"
    }
    return [_load_font_asset(spec, codepoints) for spec in specs]


def _load_font_asset(spec: dict[str, str], codepoints: set[int]) -> FontAsset:
    path = Path(spec["filename"])
    raw = _read_hash_bound_file(path, spec)
    if raw[:4] not in _ALLOWED_SFNT_MAGIC:
        _enhancement(
            "Only single-face sfnt TrueType fonts with glyf outlines are supported.",
            font_id=spec["id"],
            capability="pdf.embedded-truetype",
        )
    try:
        font = TTFont(BytesIO(raw), lazy=False, recalcTimestamp=False)
    except (TTLibError, KeyError, ValueError) as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "The font asset is not a valid TrueType font.",
            details={"font_id": spec["id"]},
        ) from error
    try:
        _validate_font(font, spec["id"])
        source_cmap = dict(font.getBestCmap() or {})
        names = _font_names(font)
        if "fvar" in font:
            defaults = {
                axis.axisTag: axis.defaultValue
                for axis in font["fvar"].axes
            }
            font = instantiateVariableFont(font, defaults, inplace=False, optimize=True)
        used_codepoints = sorted(codepoints.intersection(source_cmap))
        subset_bytes = _subset_font(font, used_codepoints)
        subset_font = TTFont(BytesIO(subset_bytes), lazy=False, recalcTimestamp=False)
        try:
            _validate_font(subset_font, spec["id"])
            head = subset_font["head"]
            hhea = subset_font["hhea"]
            os2 = subset_font["OS/2"]
            post = subset_font["post"]
            return FontAsset(
                id=spec["id"],
                path=path,
                source_sha256=spec["sha256"],
                subset_sha256=hashlib.sha256(subset_bytes).hexdigest(),
                data=subset_bytes,
                cmap=source_cmap,
                postscript_name=names["postscript"],
                license=names["license"],
                units_per_em=int(head.unitsPerEm),
                ascent=int(hhea.ascent),
                descent=int(hhea.descent),
                cap_height=int(
                    os2.sCapHeight if hasattr(os2, "sCapHeight") else hhea.ascent
                ),
                bbox=(int(head.xMin), int(head.yMin), int(head.xMax), int(head.yMax)),
                italic_angle=float(post.italicAngle),
                glyph_count=len(subset_font.getGlyphOrder()),
            )
        finally:
            subset_font.close()
    finally:
        font.close()


def _read_hash_bound_file(path: Path, spec: dict[str, str]) -> bytes:
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise OSError("not a non-empty regular file")
        if before.st_size > MAX_FONT_BYTES:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "The font asset exceeds the byte limit.",
                details={"font_id": spec["id"], "max_bytes": MAX_FONT_BYTES},
            )
        raw = path.read_bytes()
        after = path.stat()
    except DocumentSkillsError:
        raise
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "The font asset could not be read as a stable local file.",
            details={"font_id": spec["id"]},
        ) from error
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or len(raw) != before.st_size:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "The font asset changed while it was being read.",
            details={"font_id": spec["id"]},
        )
    actual = hashlib.sha256(raw).hexdigest()
    if actual != spec["sha256"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "The font asset SHA-256 does not match the request.",
            details={"font_id": spec["id"], "actual_sha256": actual},
        )
    return raw


def _validate_font(font: TTFont, font_id: str) -> None:
    required = {"head", "hhea", "hmtx", "maxp", "cmap", "name", "OS/2", "glyf", "loca"}
    missing = sorted(required.difference(font.keys()))
    glyph_count = len(font.getGlyphOrder())
    if missing or glyph_count > MAX_FONT_GLYPHS:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "The TrueType font is missing required bounded tables.",
            details={"font_id": font_id, "missing_tables": missing},
        )
    fs_type = int(font["OS/2"].fsType)
    if fs_type & _FORBIDDEN_EMBEDDING_BITS:
        _enhancement(
            "The font license flags do not permit this embedded subset.",
            font_id=font_id,
            fs_type=fs_type,
            capability="pdf.embedded-font-license",
        )


def _subset_font(font: TTFont, codepoints: list[int]) -> bytes:
    options = subset.Options()
    options.canonical_order = True
    options.hinting = True
    options.layout_closure = True
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    options.name_languages = [0x0409]
    options.notdef_glyph = True
    options.notdef_outline = True
    options.recalc_timestamp = False
    options.recommended_glyphs = True
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=codepoints)
    subsetter.subset(font)
    if "head" in font:
        font["head"].created = 0
        font["head"].modified = 0
    output = BytesIO()
    font.save(output, reorderTables=True)
    return output.getvalue()


def _font_names(font: TTFont) -> dict[str, str]:
    postscript = _first_name(font, 6) or _first_name(font, 1) or "ElftiaEmbeddedFont"
    postscript = "".join(
        character
        for character in postscript
        if character.isascii() and (character.isalnum() or character in "-_" )
    ) or "ElftiaEmbeddedFont"
    license_text = _first_name(font, 14) or _first_name(font, 13) or "unspecified"
    return {"postscript": postscript[:120], "license": license_text[:2_048]}


def _first_name(font: TTFont, name_id: int) -> str | None:
    values: list[str] = []
    for record in font["name"].names:
        if record.nameID != name_id:
            continue
        try:
            value = record.toUnicode().strip()
        except (UnicodeDecodeError, UnicodeError):
            continue
        if value and value not in values:
            values.append(value)
    return sorted(values)[0] if values else None


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
