"""Generate deterministic provider-independent PDF completion fixtures."""

import argparse
from io import BytesIO
import hashlib
import json
from pathlib import Path
import zlib

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from PIL import Image, ImageDraw, ImageFont

RECIPE = "tests/fixtures/recipes/pdf_completion_fixtures.py"
DEPENDENCIES = [
    "tests/fixtures/pdf-fonts/elftia-pdf-arabic-test.ttf",
    "tests/fixtures/pdf-fonts/elftia-pdf-cjk-test.ttf",
]
FIXED_FONT_TIMESTAMP = 2_082_844_800


def generate(output: Path, fixture_root: Path) -> list[dict[str, object]]:
    """Write the full matrix and return registry-ready records."""
    output.mkdir(parents=True, exist_ok=True)
    cjk_font = fixture_root / "pdf-fonts" / "elftia-pdf-cjk-test.ttf"
    arabic_font = fixture_root / "pdf-fonts" / "elftia-pdf-arabic-test.ttf"
    assets: dict[str, bytes] = {
        "ocr-scanned.pdf": _image_pdf(_english_scan()),
        "ocr-mixed.pdf": _image_pdf(_english_scan(), native_text="Native layer"),
        "ocr-rotated.pdf": _image_pdf(_english_scan(), rotation=90),
        "ocr-cjk-rtl.pdf": _image_pdf(_unicode_scan(cjk_font, arabic_font)),
        "ocr-multi-column.pdf": _image_pdf(_multi_column_scan()),
        "ocr-low-quality.pdf": _image_pdf(_low_quality_scan()),
        "exif-orientation-6.jpg": _exif_jpeg(),
    }
    emoji_font = _emoji_font()
    assets["emoji-success.ttf"] = emoji_font
    assets["emoji-success.pdf"] = _emoji_pdf(emoji_font)
    assets.update(_malformed_corpus())
    assets["oracles.json"] = _oracle_bytes()
    for name, payload in assets.items():
        (output / name).write_bytes(payload)
    return [_record(name, payload) for name, payload in sorted(assets.items())]


def _english_scan() -> Image.Image:
    image = Image.new("L", (900, 260), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=34)
    draw.text((35, 35), "SCANNED INVOICE 2026", font=font, fill=0)
    draw.text((35, 100), "TOTAL 42.50", font=font, fill=20)
    draw.rectangle((30, 25, 620, 155), outline=80, width=2)
    return image


def _unicode_scan(cjk_path: Path, arabic_path: Path) -> Image.Image:
    image = Image.new("L", (1000, 300), 255)
    draw = ImageDraw.Draw(image)
    cjk = ImageFont.truetype(str(cjk_path), 54)
    arabic = ImageFont.truetype(str(arabic_path), 54)
    draw.text((35, 30), "中文测试 你好世界", font=cjk, fill=0)
    # Basic layout is intentional: this is an OCR input, not a shaping oracle.
    draw.text((965, 125), "مرحبا بالعالم", font=arabic, fill=0, anchor="ra")
    return image


def _multi_column_scan() -> Image.Image:
    image = Image.new("L", (1000, 520), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=26)
    for row, text in enumerate(("LEFT ONE", "LEFT TWO", "LEFT THREE")):
        draw.text((35, 45 + row * 90), text, font=font, fill=0)
    for row, text in enumerate(("RIGHT ONE", "RIGHT TWO", "RIGHT THREE")):
        draw.text((555, 45 + row * 90), text, font=font, fill=0)
    draw.line((500, 25, 500, 390), fill=160, width=2)
    return image


def _low_quality_scan() -> Image.Image:
    image = Image.new("L", (180, 52), 228)
    draw = ImageDraw.Draw(image)
    draw.text((5, 8), "FAINT 123", font=ImageFont.load_default(), fill=125)
    for x in range(0, image.width, 7):
        image.putpixel((x, (x * 11) % image.height), 205)
    return image


def _image_pdf(
    image: Image.Image,
    *,
    native_text: str | None = None,
    rotation: int = 0,
) -> bytes:
    grayscale = image.convert("L")
    compressed = zlib.compress(grayscale.tobytes(), level=9)
    image_width = 540
    image_height = max(1, round(image_width * image.height / image.width))
    operators = (
        f"q {image_width} 0 0 {image_height} 36 520 cm /Im1 Do Q\n"
    )
    if native_text is not None:
        operators += f"BT /F1 16 Tf 36 490 Td ({native_text}) Tj ET\n"
    content = operators.encode("ascii")
    rotate = f" /Rotate {rotation}" if rotation else ""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            + rotate.encode("ascii")
            + b" /Resources << /XObject << /Im1 5 0 R >> "
            b"/Font << /F1 6 0 R >> >> /Contents 4 0 R >>"
        ),
        _stream(content),
        _stream(
            compressed,
            (
                f"/Type /XObject /Subtype /Image /Width {grayscale.width} "
                f"/Height {grayscale.height} /ColorSpace /DeviceGray "
                "/BitsPerComponent 8 /Filter /FlateDecode"
            ),
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    return _assemble_pdf(objects)


def _exif_jpeg() -> bytes:
    image = Image.new("RGB", (48, 32))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = ((x * 5) % 256, (y * 7) % 256, ((x + y) * 3) % 256)
    exif = Image.Exif()
    exif[274] = 6
    output = BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=90,
        subsampling=0,
        optimize=False,
        progressive=False,
        exif=exif,
    )
    return output.getvalue()


def _emoji_font() -> bytes:
    builder = FontBuilder(1000, isTTF=True)
    glyph_order = [".notdef", "space", "u1F600"]
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap({0x20: "space", 0x1F600: "u1F600"})
    glyphs = {".notdef": _box_glyph(80, 0, 720, 700), "space": _empty_glyph()}
    glyphs["u1F600"] = _smile_glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (1000, 0) for name in glyph_order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({
        "familyName": "Elftia Emoji Fixture",
        "styleName": "Regular",
        "uniqueFontIdentifier": "2026;ELFTIA;EmojiFixture-Regular",
        "fullName": "Elftia Emoji Fixture Regular",
        "psName": "ElftiaEmojiFixture-Regular",
        "version": "Version 1.000",
    })
    builder.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
    )
    builder.setupPost()
    builder.setupMaxp()
    builder.font["head"].created = FIXED_FONT_TIMESTAMP
    builder.font["head"].modified = FIXED_FONT_TIMESTAMP
    output = BytesIO()
    builder.font.save(output, reorderTables=True)
    return output.getvalue()


def _empty_glyph():
    return TTGlyphPen(None).glyph()


def _box_glyph(left: int, bottom: int, right: int, top: int):
    pen = TTGlyphPen(None)
    pen.moveTo((left, bottom))
    pen.lineTo((right, bottom))
    pen.lineTo((right, top))
    pen.lineTo((left, top))
    pen.closePath()
    return pen.glyph()


def _smile_glyph():
    pen = TTGlyphPen(None)
    pen.moveTo((100, 100))
    pen.lineTo((900, 100))
    pen.lineTo((900, 700))
    pen.lineTo((100, 700))
    pen.closePath()
    for left in (280, 620):
        pen.moveTo((left, 500))
        pen.lineTo((left + 100, 500))
        pen.lineTo((left + 100, 600))
        pen.lineTo((left, 600))
        pen.closePath()
    pen.moveTo((280, 320))
    pen.lineTo((720, 320))
    pen.lineTo((650, 220))
    pen.lineTo((350, 220))
    pen.closePath()
    return pen.glyph()


def _emoji_pdf(font_bytes: bytes) -> bytes:
    content = b"BT /Emoji 72 Tf 72 650 Td <0002> Tj ET\n"
    cmap = (
        b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        b"/CMapName /ElftiaEmoji def\n/CMapType 2 def\n"
        b"1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        b"1 beginbfchar\n<0002> <D83DDE00>\nendbfchar\n"
        b"endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /Emoji 5 0 R >> >> /Contents 4 0 R >>",
        _stream(content),
        b"<< /Type /Font /Subtype /Type0 /BaseFont /ElftiaEmojiFixture-Regular "
        b"/Encoding /Identity-H /DescendantFonts [6 0 R] /ToUnicode 9 0 R >>",
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /ElftiaEmojiFixture-Regular "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        b"/FontDescriptor 7 0 R /CIDToGIDMap /Identity /DW 1000 /W [2 [1000]] >>",
        b"<< /Type /FontDescriptor /FontName /ElftiaEmojiFixture-Regular /Flags 4 "
        b"/FontBBox [0 0 1000 800] /ItalicAngle 0 /Ascent 800 /Descent -200 "
        b"/CapHeight 700 /StemV 80 /FontFile2 8 0 R >>",
        _stream(font_bytes, f"/Length1 {len(font_bytes)}"),
        _stream(cmap),
    ]
    return _assemble_pdf(objects)


def _malformed_corpus() -> dict[str, bytes]:
    return {
        "provider-malformed-truncated.bin": b'{"nonce":"fixture","result":',
        "provider-malformed-binding.bin": (
            b'{"command":"pdf.ocr","nonce":"wrong","result":{}}\n'
        ),
        "provider-malformed-binary.bin": b"\x00\xffPDF_PROVIDER\x80\n",
    }


def _oracle_bytes() -> bytes:
    value = {
        "schema_version": "1.0",
        "provider_claim": "input-only-no-ocr-accuracy-claim",
        "cases": [
            _case("ocr-scanned.pdf", "scanned", 0, ["SCANNED INVOICE 2026", "TOTAL 42.50"]),
            _case("ocr-mixed.pdf", "mixed", 0, ["Native layer", "SCANNED INVOICE 2026"]),
            _case("ocr-rotated.pdf", "rotated", 90, ["SCANNED INVOICE 2026"]),
            _case("ocr-cjk-rtl.pdf", "cjk-rtl", 0, ["中文测试 你好世界", "مرحبا بالعالم"]),
            _case("ocr-multi-column.pdf", "multi-column", 0, [
                "LEFT ONE", "LEFT TWO", "LEFT THREE",
                "RIGHT ONE", "RIGHT TWO", "RIGHT THREE",
            ]),
            _case("ocr-low-quality.pdf", "low-quality", 0, ["FAINT 123"]),
        ],
        "assets": {
            "exif-orientation-6.jpg": {"exif_orientation": 6, "stored_size": [48, 32]},
            "emoji-success.ttf": {"required_codepoints": [32, 128512]},
            "emoji-success.pdf": {"unicode": "😀", "embedded_font": True},
        },
        "malformed_provider_outputs": {
            "provider-malformed-truncated.bin": "truncated-json",
            "provider-malformed-binding.bin": "nonce-binding-mismatch",
            "provider-malformed-binary.bin": "non-utf8-output",
        },
    }
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _case(path: str, kind: str, rotation: int, text: list[str]) -> dict[str, object]:
    return {
        "path": path,
        "kind": kind,
        "page_count": 1,
        "rotation": rotation,
        "expected_text": text,
        "oracle_scope": "provider-independent-input-and-expected-semantics",
    }


def _stream(payload: bytes, entries: str = "") -> bytes:
    prefix = (entries + " ") if entries else ""
    return (
        f"<< {prefix}/Length {len(payload)} >>\nstream\n".encode("ascii")
        + payload
        + b"\nendstream"
    )


def _assemble_pdf(values: list[bytes]) -> bytes:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets = [0]
    for number, value in enumerate(values, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{number} 0 obj\n".encode("ascii") + value + b"\nendobj\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {len(values) + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for offset in offsets[1:]:
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {len(values) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return header + bytes(body) + bytes(xref)


def _record(name: str, payload: bytes) -> dict[str, object]:
    formats = {".pdf": "pdf", ".jpg": "jpeg", ".ttf": "ttf", ".json": "json"}
    purposes = {
        "ocr-scanned.pdf": "Image-only scanned-page OCR input with deterministic text oracle",
        "ocr-mixed.pdf": "Mixed native-text and scanned-image OCR routing input",
        "ocr-rotated.pdf": "Rotated scanned-page OCR normalization input",
        "ocr-cjk-rtl.pdf": "Raster CJK and RTL-script OCR input without accuracy claims",
        "ocr-multi-column.pdf": "Two-column scanned reading-order OCR input",
        "ocr-low-quality.pdf": "Low-resolution low-contrast OCR failure/degradation input",
        "exif-orientation-6.jpg": "JPEG EXIF orientation normalization input",
        "emoji-success.ttf": "Original minimal TrueType font containing U+1F600",
        "emoji-success.pdf": "Embedded-font PDF mapping a CID to U+1F600",
        "oracles.json": "Machine-readable expectations and no-provider-claim boundary",
        "provider-malformed-truncated.bin": "Truncated provider result envelope rejection input",
        "provider-malformed-binding.bin": "Wrong nonce provider result envelope rejection input",
        "provider-malformed-binary.bin": "Non-UTF-8 provider output rejection input",
    }
    classification = "provider-negative" if name.startswith("provider-") else "benign"
    if name == "oracles.json":
        classification = "oracle"
    return {
        "authorship": "original-elftia",
        "format": formats.get(Path(name).suffix, "bin"),
        "license": "GPL-3.0",
        "origin": "generated",
        "path": f"pdf-completion/{name}",
        "purpose": purposes[name],
        "recipe": RECIPE,
        "recipe_dependencies": DEPENDENCIES,
        "redistribution_allowed": True,
        "security_classification": classification,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    args = parser.parse_args()
    records = generate(args.output, args.fixture_root)
    print(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
