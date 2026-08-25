"""Deterministic Type0/CIDFontType2 embedding for shaped TrueType glyphs."""

from dataclasses import dataclass, field
import hashlib
from io import BytesIO
from typing import Any, Protocol

from fontTools.ttLib import TTFont

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .font_assets import FontAsset
from .create_layout import pdf_number

MAX_SYNTHETIC_CIDS = 32_768


class PdfObjectWriter(Protocol):
    def reserve_object(self) -> int: ...

    def replace_object(self, obj_num: int, content: bytes) -> None: ...

    def add_object(self, content: bytes) -> int: ...

    def add_stream_object(self, dictionary: bytes, stream_data: bytes) -> int: ...


@dataclass(frozen=True)
class _CidRecord:
    cid: int
    glyph_id: int
    text: str
    width: int


@dataclass
class EmbeddedFont:
    """One reserved Type0 resource populated as shaped glyphs are emitted."""

    asset: FontAsset
    resource_name: str
    root_object: int
    base_font: str
    glyph_widths: tuple[int, ...]
    _records: list[_CidRecord] = field(default_factory=list)
    _cid_by_key: dict[tuple[int, str], int] = field(default_factory=dict)

    def cid_for(self, glyph_id: int, text: str) -> int:
        key = (glyph_id, text)
        existing = self._cid_by_key.get(key)
        if existing is not None:
            return existing
        if glyph_id < 0 or glyph_id > 65_535 or glyph_id >= len(self.glyph_widths):
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "A shaped glyph id is outside the embedded TrueType face.",
                details={"font_id": self.asset.id, "glyph_id": glyph_id},
            )
        cid = len(self._records) + 1
        if cid > MAX_SYNTHETIC_CIDS:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "The embedded font exceeded the synthetic CID limit.",
                details={"font_id": self.asset.id, "max_cids": MAX_SYNTHETIC_CIDS},
            )
        record = _CidRecord(
            cid=cid,
            glyph_id=glyph_id,
            text=text,
            width=self.glyph_widths[glyph_id],
        )
        self._records.append(record)
        self._cid_by_key[key] = cid
        return cid

    def finalize(self, writer: PdfObjectWriter) -> None:
        font_file = writer.add_stream_object(
            (
                f"<< /Length {len(self.asset.data)} "
                f"/Length1 {len(self.asset.data)} >>"
            ).encode("ascii"),
            self.asset.data,
        )
        descriptor = writer.add_object(self._font_descriptor(font_file))
        cid_to_gid_data = self._cid_to_gid_map()
        cid_to_gid = writer.add_stream_object(
            f"<< /Length {len(cid_to_gid_data)} >>".encode("ascii"),
            cid_to_gid_data,
        )
        descendant = writer.add_object(
            self._descendant_font(descriptor, cid_to_gid)
        )
        to_unicode_data = self._to_unicode_cmap()
        to_unicode = writer.add_stream_object(
            f"<< /Length {len(to_unicode_data)} >>".encode("ascii"),
            to_unicode_data,
        )
        writer.replace_object(
            self.root_object,
            (
                f"<< /Type /Font /Subtype /Type0 /BaseFont /{self.base_font} "
                f"/Encoding /Identity-H /DescendantFonts [{descendant} 0 R] "
                f"/ToUnicode {to_unicode} 0 R >>"
            ).encode("ascii"),
        )

    def evidence(self) -> dict[str, Any]:
        return {
            "id": self.asset.id,
            "resource": f"/{self.resource_name}",
            "font_object": self.root_object,
            "base_font": self.base_font,
            "source_sha256": self.asset.source_sha256,
            "subset_sha256": self.asset.subset_sha256,
            "subset": True,
            "license": self.asset.license,
            "glyph_count": self.asset.glyph_count,
            "mapped_cids": len(self._records),
        }

    def _font_descriptor(self, font_file: int) -> bytes:
        scale = 1000.0 / self.asset.units_per_em
        bbox = " ".join(
            pdf_number(value * scale)
            for value in self.asset.bbox
        )
        return (
            f"<< /Type /FontDescriptor /FontName /{self.base_font} /Flags 4 "
            f"/FontBBox [{bbox}] /ItalicAngle {pdf_number(self.asset.italic_angle)} "
            f"/Ascent {pdf_number(self.asset.ascent * scale)} "
            f"/Descent {pdf_number(self.asset.descent * scale)} "
            f"/CapHeight {pdf_number(self.asset.cap_height * scale)} "
            f"/StemV 80 /FontFile2 {font_file} 0 R >>"
        ).encode("ascii")

    def _descendant_font(self, descriptor: int, cid_to_gid: int) -> bytes:
        widths = " ".join(
            f"{record.cid} [{record.width}]"
            for record in self._records
        )
        width_entry = f" /W [{widths}]" if widths else ""
        return (
            f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{self.base_font} "
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
            f"/FontDescriptor {descriptor} 0 R /DW 1000{width_entry} "
            f"/CIDToGIDMap {cid_to_gid} 0 R >>"
        ).encode("ascii")

    def _cid_to_gid_map(self) -> bytes:
        maximum = max((record.cid for record in self._records), default=0)
        values = [0] * (maximum + 1)
        for record in self._records:
            values[record.cid] = record.glyph_id
        return b"".join(value.to_bytes(2, "big") for value in values)

    def _to_unicode_cmap(self) -> bytes:
        lines = [
            "/CIDInit /ProcSet findresource begin",
            "12 dict begin",
            "begincmap",
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
            f"/CMapName /{self.base_font}-UCS def",
            "/CMapType 2 def",
            "1 begincodespacerange",
            "<0000> <FFFF>",
            "endcodespacerange",
        ]
        for start in range(0, len(self._records), 100):
            batch = self._records[start : start + 100]
            lines.append(f"{len(batch)} beginbfchar")
            for record in batch:
                target = record.text.encode("utf-16-be").hex().upper()
                lines.append(f"<{record.cid:04X}> <{target}>")
            lines.append("endbfchar")
        lines.extend([
            "endcmap",
            "CMapName currentdict /CMap defineresource pop",
            "end",
            "end",
        ])
        return ("\n".join(lines) + "\n").encode("ascii")


class EmbeddedFontSet:
    """Request-scoped embedded font resources with deferred finalization."""

    def __init__(
        self,
        writer: PdfObjectWriter,
        assets: list[FontAsset],
        *,
        resource_prefix: str = "F",
        resource_start: int = 5,
    ) -> None:
        self.fonts: list[EmbeddedFont] = []
        for index, asset in enumerate(assets, start=resource_start):
            self.fonts.append(EmbeddedFont(
                asset=asset,
                resource_name=f"{resource_prefix}{index}",
                root_object=writer.reserve_object(),
                base_font=_base_font_name(asset),
                glyph_widths=_glyph_widths(asset),
            ))
        self.by_id = {font.asset.id: font for font in self.fonts}

    def page_resource_entries(self) -> str:
        return " ".join(
            f"/{font.resource_name} {font.root_object} 0 R"
            for font in self.fonts
        )

    def finalize(self, writer: PdfObjectWriter) -> None:
        for font in self.fonts:
            font.finalize(writer)

    def evidence(self) -> list[dict[str, Any]]:
        return [font.evidence() for font in self.fonts]


def _base_font_name(asset: FontAsset) -> str:
    digest = hashlib.sha256(
        f"{asset.source_sha256}:{asset.subset_sha256}".encode("ascii")
    ).digest()
    tag = "".join(chr(ord("A") + byte % 26) for byte in digest[:6])
    return f"{tag}+{asset.postscript_name}"


def _glyph_widths(asset: FontAsset) -> tuple[int, ...]:
    font = TTFont(BytesIO(asset.data), lazy=False, recalcTimestamp=False)
    try:
        glyph_order = font.getGlyphOrder()
        metrics = font["hmtx"].metrics
        return tuple(
            round(metrics[name][0] * 1000 / asset.units_per_em)
            for name in glyph_order
        )
    finally:
        font.close()
