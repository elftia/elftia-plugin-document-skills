"""Deterministic raster and observation fixtures for PPTX reconstruction."""

from __future__ import annotations

import struct
import zlib

from tests.support.pptx_ecosystem_fixture import (
    EcosystemFixtureWriter,
    FixtureMetadata,
)


_WIDTH = 400
_HEIGHT = 225
_RECIPE = (
    "uv run --project plugin --frozen python "
    "plugin/tests/fixtures/pptx/ecosystem_bc/generate.py "
    "<presentation-contract-root> --write"
)
_FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "N": ("10001", "11001", "11001", "10101", "10011", "10011", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
}


def write_reconstruction_fixtures(writer: EcosystemFixtureWriter) -> list[str]:
    """Write B-REC-01/02 image and expected-observation pairs."""
    cases = (
        (
            "B-REC-01",
            "synthetic-cards",
            _synthetic_cards_png(),
            _synthetic_cards_observations(),
            "Layered synthetic cards with confident editable text and shapes.",
            (
                "all observations exceed the default confidence threshold",
                "stable reading order alternates each card before its text",
                "no observation proposes an uncropped whole-slide raster",
            ),
        ),
        (
            "B-REC-02",
            "low-confidence",
            _low_confidence_png(),
            _low_confidence_observations(),
            "Mixed-confidence cards with one isolated low-confidence text region.",
            (
                "exactly one observation is below the default confidence threshold",
                "the low-confidence source region is smaller than and separate from the editable cards",
                "editable area and object-count coverage have distinct ratios",
            ),
        ),
    )
    written: list[str] = []
    for fixture_id, stem, image, observations, purpose, invariants in cases:
        common = {
            "fixture_id": fixture_id,
            "origin": "Elftia-authored deterministic raster and observation fixture.",
            "recipe": _RECIPE,
            "license": "GPL-3.0",
            "expected_operation": "pptx.reconstruct.from-image",
            "expected_consumers": ("document-skills",),
            "invariants": invariants,
        }
        writer.write_bytes(
            f"reconstruction/{stem}.png",
            image,
            FixtureMetadata(
                format="png",
                purpose=purpose,
                resource_limits={"maxBytes": 256_000},
                security_classification="benign-generated-reconstruction-raster",
                **common,
            ),
        )
        writer.write_json(
            f"reconstruction/{stem}.observations.json",
            observations,
            FixtureMetadata(
                format="json",
                purpose=f"Expected deterministic OCR/vision observations for {stem}.png.",
                resource_limits={"maxBytes": 64_000},
                security_classification="benign-generated-reconstruction-observations",
                **common,
            ),
        )
        written.append(fixture_id)
    return written


def _synthetic_cards_png() -> bytes:
    canvas = _Canvas()
    canvas.card(20, 45, 165, 135, (220, 232, 255), (36, 87, 166))
    canvas.card(215, 45, 165, 135, (226, 246, 237), (32, 128, 88))
    canvas.text(35, 68, "PLAN", (16, 32, 48), scale=3)
    canvas.text(35, 112, "BUILD", (36, 87, 166), scale=2)
    canvas.text(230, 68, "SHIP", (16, 32, 48), scale=3)
    return canvas.png()


def _low_confidence_png() -> bytes:
    canvas = _Canvas()
    canvas.card(20, 40, 150, 130, (220, 232, 255), (36, 87, 166))
    canvas.card(230, 40, 150, 80, (226, 246, 237), (32, 128, 88))
    canvas.text(35, 65, "BUILD", (16, 32, 48), scale=2)
    canvas.text(245, 65, "SHIP", (16, 32, 48), scale=2)
    canvas.card(230, 145, 110, 30, (255, 235, 214), (190, 94, 24))
    canvas.text(245, 153, "LOW", (128, 54, 15), scale=2)
    return canvas.png()


def _synthetic_cards_observations() -> dict[str, object]:
    return {
        "canvas": {"height": _HEIGHT, "width": _WIDTH},
        "elements": [
            _element("card-plan", "shape", 0, (20, 45, 165, 135), 0.99),
            _element("text-plan", "text", 1, (35, 68, 95, 24), 0.98, "PLAN"),
            _element("text-build", "text", 2, (35, 112, 90, 18), 0.96, "BUILD"),
            _element("card-ship", "shape", 3, (215, 45, 165, 135), 0.99),
            _element("text-ship", "text", 4, (230, 68, 85, 24), 0.97, "SHIP"),
        ],
    }


def _low_confidence_observations() -> dict[str, object]:
    return {
        "canvas": {"height": _HEIGHT, "width": _WIDTH},
        "elements": [
            _element("card-build", "shape", 0, (20, 40, 150, 130), 0.99),
            _element("text-build", "text", 1, (35, 65, 90, 18), 0.96, "BUILD"),
            _element("card-ship", "shape", 2, (230, 40, 150, 80), 0.98),
            _element("text-ship", "text", 3, (245, 65, 80, 18), 0.95, "SHIP"),
            _element("text-low", "text", 4, (230, 145, 110, 30), 0.42, "LOW"),
        ],
    }


def _element(
    identity: str,
    kind: str,
    order: int,
    rect: tuple[int, int, int, int],
    confidence: float,
    text: str = "",
) -> dict[str, object]:
    x, y, width, height = rect
    return {
        "confidence": confidence,
        "geometry": {"height": height, "width": width, "x": x, "y": y},
        "id": identity,
        "kind": kind,
        "reading_order": order,
        "source_region": {"height": height, "width": width, "x": x, "y": y},
        "style": {
            "border_color": "#2457A6",
            "border_width": 2,
            "color": "#102030",
            "fill": "#DCE8FF",
            "font_family": "Arial",
            "font_size": 28,
            "font_weight": 600,
            "radius": 8,
            "text_align": "left",
        },
        "text": text,
    }


class _Canvas:
    def __init__(self) -> None:
        self.pixels = bytearray((242, 244, 248) * _WIDTH * _HEIGHT)

    def card(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        fill: tuple[int, int, int],
        border: tuple[int, int, int],
    ) -> None:
        self.rectangle(x, y, width, height, border)
        self.rectangle(x + 2, y + 2, width - 4, height - 4, fill)

    def rectangle(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        color: tuple[int, int, int],
    ) -> None:
        row = bytes(color) * width
        for target_y in range(y, y + height):
            start = (target_y * _WIDTH + x) * 3
            self.pixels[start : start + len(row)] = row

    def text(
        self,
        x: int,
        y: int,
        value: str,
        color: tuple[int, int, int],
        *,
        scale: int,
    ) -> None:
        cursor = x
        for character in value:
            glyph = _FONT[character]
            for row_index, row in enumerate(glyph):
                for column_index, pixel in enumerate(row):
                    if pixel == "1":
                        self.rectangle(
                            cursor + column_index * scale,
                            y + row_index * scale,
                            scale,
                            scale,
                            color,
                        )
            cursor += 6 * scale

    def png(self) -> bytes:
        raw = b"".join(
            b"\x00" + self.pixels[row * _WIDTH * 3 : (row + 1) * _WIDTH * 3]
            for row in range(_HEIGHT)
        )
        header = struct.pack(">IIBBBBB", _WIDTH, _HEIGHT, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(raw, level=9))
            + _chunk(b"IEND", b"")
        )


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return (
        struct.pack(">I", len(payload))
        + body
        + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    )


__all__ = ["write_reconstruction_fixtures"]
