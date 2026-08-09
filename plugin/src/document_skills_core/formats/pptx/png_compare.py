"""Bounded dependency-free PNG decoding and normalized visual comparison."""

import struct
import zlib

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_ENCODED_BYTES = 16 * 1024 * 1024
_MAX_PIXELS = 10_000_000
_GRID_WIDTH = 96
_GRID_HEIGHT = 54
MEAN_ABSOLUTE_ERROR_MAX = 0.08
CHANGED_PIXEL_RATIO_MAX = 0.2
CHANGED_PIXEL_DELTA = 0.12
ASPECT_RATIO_DELTA_MAX = 0.01


def compare_png(source: bytes, rendered: bytes) -> dict[str, object]:
    source_width, source_height, source_rgba = _decode_png(source)
    rendered_width, rendered_height, rendered_rgba = _decode_png(rendered)
    source_ratio = source_width / source_height
    rendered_ratio = rendered_width / rendered_height
    aspect_delta = abs(source_ratio - rendered_ratio) / source_ratio
    total_delta = 0.0
    changed = 0
    sample_count = _GRID_WIDTH * _GRID_HEIGHT
    for grid_y in range(_GRID_HEIGHT):
        source_y = min(source_height - 1, grid_y * source_height // _GRID_HEIGHT)
        rendered_y = min(rendered_height - 1, grid_y * rendered_height // _GRID_HEIGHT)
        for grid_x in range(_GRID_WIDTH):
            source_x = min(source_width - 1, grid_x * source_width // _GRID_WIDTH)
            rendered_x = min(rendered_width - 1, grid_x * rendered_width // _GRID_WIDTH)
            source_rgb = _composite_white(source_rgba, source_width, source_x, source_y)
            rendered_rgb = _composite_white(
                rendered_rgba,
                rendered_width,
                rendered_x,
                rendered_y,
            )
            delta = sum(abs(left - right) for left, right in zip(source_rgb, rendered_rgb)) / 765
            total_delta += delta
            changed += delta > CHANGED_PIXEL_DELTA
    mean_error = total_delta / sample_count
    changed_ratio = changed / sample_count
    within = (
        aspect_delta <= ASPECT_RATIO_DELTA_MAX
        and mean_error <= MEAN_ABSOLUTE_ERROR_MAX
        and changed_ratio <= CHANGED_PIXEL_RATIO_MAX
    )
    return {
        "source_size": {"width": source_width, "height": source_height},
        "rendered_size": {"width": rendered_width, "height": rendered_height},
        "mean_absolute_error": round(mean_error, 6),
        "changed_pixel_ratio": round(changed_ratio, 6),
        "aspect_ratio_delta": round(aspect_delta, 6),
        "within_thresholds": within,
    }


def visual_thresholds() -> dict[str, object]:
    return {
        "mean_absolute_error_max": MEAN_ABSOLUTE_ERROR_MAX,
        "changed_pixel_ratio_max": CHANGED_PIXEL_RATIO_MAX,
        "changed_pixel_delta": CHANGED_PIXEL_DELTA,
        "aspect_ratio_delta_max": ASPECT_RATIO_DELTA_MAX,
        "sample_grid": {"width": _GRID_WIDTH, "height": _GRID_HEIGHT},
    }


def _decode_png(payload: bytes) -> tuple[int, int, bytes]:
    if not 0 < len(payload) <= _MAX_ENCODED_BYTES or not payload.startswith(_SIGNATURE):
        raise ValueError("PNG payload is missing or exceeds policy.")
    offset = len(_SIGNATURE)
    header: tuple[int, int, int, int, int, int, int] | None = None
    palette = b""
    transparency = b""
    compressed = bytearray()
    saw_end = False
    while offset < len(payload):
        if offset + 12 > len(payload):
            raise ValueError("PNG chunk framing is invalid.")
        size = struct.unpack(">I", payload[offset:offset + 4])[0]
        kind = payload[offset + 4:offset + 8]
        end = offset + 12 + size
        if end > len(payload):
            raise ValueError("PNG chunk exceeds payload.")
        chunk = payload[offset + 8:offset + 8 + size]
        expected_crc = struct.unpack(">I", payload[offset + 8 + size:end])[0]
        if zlib.crc32(kind + chunk) & 0xFFFFFFFF != expected_crc:
            raise ValueError("PNG chunk checksum is invalid.")
        if kind == b"IHDR":
            if header is not None or size != 13:
                raise ValueError("PNG header is invalid.")
            header = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"PLTE":
            palette = chunk
        elif kind == b"tRNS":
            transparency = chunk
        elif kind == b"IDAT":
            compressed.extend(chunk)
            if len(compressed) > _MAX_ENCODED_BYTES:
                raise ValueError("PNG compressed data exceeds policy.")
        elif kind == b"IEND":
            saw_end = True
            break
        offset = end
    if header is None or not saw_end or not compressed:
        raise ValueError("PNG required chunks are missing.")
    width, height, bit_depth, color_type, compression, filter_method, interlace = header
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if (
        channels is None
        or bit_depth != 8
        or compression != 0
        or filter_method != 0
        or interlace != 0
        or width <= 0
        or height <= 0
        or width * height > _MAX_PIXELS
    ):
        raise ValueError("PNG format is unsupported for bounded comparison.")
    row_bytes = width * channels
    expected_bytes = height * (row_bytes + 1)
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(bytes(compressed), expected_bytes + 1)
    if len(raw) != expected_bytes or not decompressor.eof or decompressor.unused_data:
        raise ValueError("PNG decompressed data is invalid.")
    pixels = _unfilter(raw, height, row_bytes, channels)
    return width, height, _to_rgba(pixels, color_type, palette, transparency)


def _unfilter(raw: bytes, height: int, row_bytes: int, channels: int) -> bytes:
    result = bytearray(height * row_bytes)
    source_offset = 0
    for row_index in range(height):
        filter_type = raw[source_offset]
        source_offset += 1
        row = bytearray(raw[source_offset:source_offset + row_bytes])
        source_offset += row_bytes
        previous_start = (row_index - 1) * row_bytes
        for index in range(row_bytes):
            left = row[index - channels] if index >= channels else 0
            above = result[previous_start + index] if row_index else 0
            upper_left = result[previous_start + index - channels] if row_index and index >= channels else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 0xFF
            elif filter_type == 2:
                row[index] = (row[index] + above) & 0xFF
            elif filter_type == 3:
                row[index] = (row[index] + ((left + above) // 2)) & 0xFF
            elif filter_type == 4:
                row[index] = (row[index] + _paeth(left, above, upper_left)) & 0xFF
            elif filter_type != 0:
                raise ValueError("PNG row filter is invalid.")
        start = row_index * row_bytes
        result[start:start + row_bytes] = row
    return bytes(result)


def _to_rgba(pixels: bytes, color_type: int, palette: bytes, transparency: bytes) -> bytes:
    result = bytearray()
    if color_type == 6:
        return pixels
    if color_type == 2:
        for offset in range(0, len(pixels), 3):
            result.extend((*pixels[offset:offset + 3], 255))
    elif color_type == 0:
        for value in pixels:
            result.extend((value, value, value, 255))
    elif color_type == 4:
        for offset in range(0, len(pixels), 2):
            value, alpha = pixels[offset:offset + 2]
            result.extend((value, value, value, alpha))
    else:
        if not palette or len(palette) % 3 != 0:
            raise ValueError("PNG palette is invalid.")
        for index in pixels:
            offset = index * 3
            if offset + 3 > len(palette):
                raise ValueError("PNG palette index is invalid.")
            result.extend((*palette[offset:offset + 3], transparency[index] if index < len(transparency) else 255))
    return bytes(result)


def _composite_white(rgba: bytes, width: int, x: int, y: int) -> tuple[int, int, int]:
    offset = (y * width + x) * 4
    red, green, blue, alpha = rgba[offset:offset + 4]
    return tuple((channel * alpha + 255 * (255 - alpha)) // 255 for channel in (red, green, blue))


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_delta = abs(estimate - left)
    above_delta = abs(estimate - above)
    upper_left_delta = abs(estimate - upper_left)
    if left_delta <= above_delta and left_delta <= upper_left_delta:
        return left
    return above if above_delta <= upper_left_delta else upper_left
