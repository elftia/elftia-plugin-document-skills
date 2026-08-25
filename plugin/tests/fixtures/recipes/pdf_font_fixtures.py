"""Build small, deterministic OFL font fixtures for PDF Unicode tests.

The caller supplies exact upstream font files and SHA-256 identities. This
recipe performs no network access and renames the subsets so reserved upstream
font names are not used by the distributed modified fixtures.
"""

import argparse
from io import BytesIO
import hashlib
import json
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

CJK_TEXT = "PDF Unicode Latin 中文测试 标题段落 你好世界"
ARABIC_TEXT = "PDF Unicode Latin مرحبا بالعالم العربية 123"
FIXED_FONT_TIMESTAMP = 2_082_844_800


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cjk-source", type=Path, required=True)
    parser.add_argument("--cjk-sha256", required=True)
    parser.add_argument("--arabic-source", type=Path, required=True)
    parser.add_argument("--arabic-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = [
        _build_fixture(
            args.cjk_source,
            args.cjk_sha256,
            args.output_dir / "elftia-pdf-cjk-test.ttf",
            CJK_TEXT,
            "Elftia PDF CJK Test",
            {"wght": 400.0},
        ),
        _build_fixture(
            args.arabic_source,
            args.arabic_sha256,
            args.output_dir / "elftia-pdf-arabic-test.ttf",
            ARABIC_TEXT,
            "Elftia PDF Arabic Test",
            {"wght": 400.0, "wdth": 100.0},
        ),
    ]
    manifest = {
        "schema_version": "1.0",
        "license": "OFL-1.1",
        "fixtures": records,
        "upstream": {
            "cjk": {
                "repository": "https://github.com/notofonts/noto-cjk",
                "revision": "f8d157532fbfaeda587e826d4cd5b21a49186f7c",
                "path": "Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf",
            },
            "arabic": {
                "repository": "https://github.com/google/fonts",
                "revision": "ec626514f79f831f1ab848a82114a0ce7e2d6372",
                "path": "ofl/notosansarabic/NotoSansArabic[wdth,wght].ttf",
            },
        },
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


def _build_fixture(
    source: Path,
    expected_sha256: str,
    output: Path,
    text: str,
    family_name: str,
    axes: dict[str, float],
) -> dict[str, object]:
    raw = source.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if source_sha256 != expected_sha256:
        raise ValueError(f"Source font hash mismatch: {source}")
    font = TTFont(BytesIO(raw), lazy=False, recalcBBoxes=False, recalcTimestamp=False)
    if "fvar" in font:
        selected_axes = {
            axis.axisTag: axes.get(axis.axisTag, axis.defaultValue)
            for axis in font["fvar"].axes
        }
        instantiateVariableFont(font, selected_axes, inplace=True, optimize=True)

    options = subset.Options()
    options.canonical_order = True
    options.glyph_names = True
    options.layout_features = ["*"]
    options.layout_scripts = ["*"]
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    options.name_languages = ["*"]
    options.notdef_glyph = True
    options.notdef_outline = True
    options.recalc_timestamp = False
    options.recommended_glyphs = True
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=text)
    subsetter.subset(font)

    _rename_font(font, family_name)
    if "head" in font:
        font["head"].created = FIXED_FONT_TIMESTAMP
        font["head"].modified = FIXED_FONT_TIMESTAMP
    buffer = BytesIO()
    font.save(buffer, reorderTables=True)
    output_bytes = buffer.getvalue()
    output.write_bytes(output_bytes)
    return {
        "filename": output.name,
        "family": family_name,
        "source_sha256": source_sha256,
        "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
        "output_bytes": len(output_bytes),
        "text": text,
    }


def _rename_font(font: TTFont, family: str) -> None:
    name_table = font["name"]
    postscript = "".join(character for character in family if character.isalnum())
    values = {
        1: family,
        2: "Regular",
        3: f"2026;ELFTIA;{postscript}-Regular",
        4: f"{family} Regular",
        6: f"{postscript}-Regular",
    }
    name_table.names = [record for record in name_table.names if record.nameID not in values]
    for name_id, value in values.items():
        name_table.setName(value, name_id, 3, 1, 0x409)


if __name__ == "__main__":
    raise SystemExit(main())
