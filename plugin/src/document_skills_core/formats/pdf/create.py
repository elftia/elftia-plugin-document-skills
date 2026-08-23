"""Styled PDF document construction via direct byte-level object assembly.

Builds a new PDF with an explicit header, Catalog, Pages tree, Page leaves,
content streams, built-in Latin font resources, a classical xref table,
trailer, and EOF marker. Documents may contain one or more pages and only
the typed blocks requested by the caller.

Module provenance: original Elftia-authored clean-room implementation.  No
pypdf, fpdf2, reportlab, or pdf-lib is used.

D12 adoption-gate: the Core text, table, vector-shape, metadata, image-resource,
content-stream, and classical-xref path is emitted by direct PDF object
construction.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from .create_layout import (
    PageLayout,
    build_text_block,
    pdf_number,
    resolve_page_layout,
    shape_evidence,
    shape_paint_operator,
    shape_path,
    shape_style_operators,
)
from .image_assets import (
    ImageAsset,
    image_xobject_dictionary,
    load_image_asset,
    soft_mask_dictionary,
)


@dataclass
class _PdfWriter:
    """Minimal PDF writer for direct byte-level construction."""
    objects: list[tuple[int, int, bytes]] = None  # (obj_num, gen_num, content_bytes)
    next_obj: int = 1

    def __post_init__(self) -> None:
        if self.objects is None:
            self.objects = []

    def add_object(self, content: bytes) -> int:
        obj_num = self.next_obj
        self.objects.append((obj_num, 0, content))
        self.next_obj += 1
        return obj_num

    def add_stream_object(self, dictionary: bytes, stream_data: bytes) -> int:
        content = dictionary + b"\nstream\n" + stream_data + b"\nendstream"
        return self.add_object(content)

    def build(self, metadata: dict[str, str]) -> bytes:
        """Assemble the complete PDF bytes with classical xref table."""
        header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
        offsets: dict[int, int] = {}
        body = bytearray()
        for obj_num, gen_num, content in self.objects:
            offsets[obj_num] = len(header) + len(body)
            body.extend(f"{obj_num} {gen_num} obj\n".encode("ascii"))
            body.extend(content)
            body.extend(b"\nendobj\n")
        # Xref table
        xref_offset = len(header) + len(body)
        max_obj = max(offsets.keys()) if offsets else 0
        xref = bytearray()
        xref.extend(b"xref\n")
        xref.extend(f"0 {max_obj + 1}\n".encode("ascii"))
        xref.extend(b"0000000000 65535 f\r\n")
        for i in range(1, max_obj + 1):
            offset = offsets.get(i, 0)
            xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
        # Trailer
        xref.extend(
            f"trailer\n<< /Size {max_obj + 1} /Root 1 0 R /Info {self.next_obj - 1} 0 R >>\n".encode("ascii")
        )
        xref.extend(f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
        return header + bytes(body) + bytes(xref)


def create_pdf(output: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Create a styled PDF document at the output path.

    Returns a creation result dict with page count, structures, and evidence.
    """
    metadata = document["metadata"]
    page_size = document["page_size"]
    pages_data = document["pages"]

    writer = _PdfWriter()

    # Obj 1: Catalog (reserve, fill later with Pages ref)
    catalog_obj = 1
    writer.next_obj = 2
    pages_obj = 2
    writer.next_obj = 3

    # Built-in Helvetica family variants used by the typed Core style subset.
    font_regular = writer.add_object(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    font_bold = writer.add_object(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    font_italic = writer.add_object(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique /Encoding /WinAnsiEncoding >>"
    )
    font_bold_italic = writer.add_object(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-BoldOblique /Encoding /WinAnsiEncoding >>"
    )

    page_object_nums: list[int] = []
    content_stream_nums: list[int] = []
    structures: dict[str, bool] = {
        "pages": True,
        "table": False,
        "image": False,
        "vector_shape": False,
        "metadata": True,
    }
    created_images: list[dict[str, Any]] = []
    created_shapes: list[dict[str, Any]] = []
    created_text_blocks: list[dict[str, Any]] = []
    page_sizes: list[list[float]] = []

    for page_idx, page_data in enumerate(pages_data):
        layout = resolve_page_layout(page_size, page_data)
        page_sizes.append([layout.width, layout.height])
        # Build content stream operators
        operators, xobjects, ext_gstates = _build_page_operators(
            page_data,
            layout,
            structures,
            writer,
            page_idx + 1,
            created_images,
            created_shapes,
            created_text_blocks,
        )
        content_bytes = operators.encode("latin-1", errors="replace")
        # Content stream object
        content_num = writer.add_stream_object(
            b"<< /Length " + str(len(content_bytes)).encode("ascii") + b" >>",
            content_bytes,
        )
        content_stream_nums.append(content_num)
        # Font dictionary
        font_dict = (
            f"<< /F1 {font_regular} 0 R /F2 {font_bold} 0 R "
            f"/F3 {font_italic} 0 R /F4 {font_bold_italic} 0 R >>"
        ).encode("ascii")
        xobject_dict = b""
        if xobjects:
            entries = " ".join(
                f"/{name} {obj_num} 0 R"
                for name, obj_num in xobjects.items()
            )
            xobject_dict = f" /XObject << {entries} >>".encode("ascii")
        ext_gstate_dict = b""
        if ext_gstates:
            entries = " ".join(
                f"/{name} {obj_num} 0 R"
                for name, obj_num in ext_gstates.items()
            )
            ext_gstate_dict = f" /ExtGState << {entries} >>".encode("ascii")
        # Page object
        page_num = writer.add_object(
            b"<< /Type /Page /Parent " + f"{pages_obj} 0 R".encode("ascii") + b" "
            + f"/MediaBox [0 0 {pdf_number(layout.width)} {pdf_number(layout.height)}]".encode("ascii") + b" "
            + f"/Contents {content_num} 0 R".encode("ascii") + b" "
            + b"/Resources << /Font " + font_dict + xobject_dict + ext_gstate_dict + b" >> >>"
        )
        page_object_nums.append(page_num)

    # Kids array for Pages
    kids = " ".join(f"{n} 0 R" for n in page_object_nums)
    pages_content = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_nums)} >>"
    ).encode("ascii")

    # Info dictionary
    title = _escape_pdf_string(metadata.get("title", ""))
    author = _escape_pdf_string(metadata.get("author", ""))
    subject = _escape_pdf_string(metadata.get("subject", ""))
    info_content = (
        f"<< /Title ({title}) /Author ({author}) /Subject ({subject}) "
        f"/Creator (Elftia Document Skills) /Producer (Elftia PDF Core) "
        f"/CreationDate (D:20260101000000+00'00') >>"
    ).encode("ascii")
    writer.add_object(info_content)

    # Now build the catalog + pages in the correct position
    # Rebuild objects with catalog at obj 1 and pages at obj 2
    writer.objects.insert(0, (1, 0, b"<< /Type /Catalog /Pages 2 0 R >>"))
    writer.objects.insert(1, (2, 0, pages_content))

    pdf_bytes = writer.build(metadata)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pdf_bytes)

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    return {
        "page_count": len(page_object_nums),
        "page_size": page_sizes[0],
        "page_sizes": page_sizes,
        "structures": structures,
        "images": created_images,
        "shapes": created_shapes,
        "text_blocks": created_text_blocks,
        "output_sha256": sha256,
        "output_bytes": len(pdf_bytes),
    }


def _build_page_operators(
    page_data: dict[str, Any],
    layout: PageLayout,
    structures: dict[str, bool],
    writer: _PdfWriter,
    page_number: int,
    created_images: list[dict[str, Any]],
    created_shapes: list[dict[str, Any]],
    created_text_blocks: list[dict[str, Any]],
) -> tuple[str, dict[str, int], dict[str, int]]:
    """Build content stream operators for a page."""
    ops: list[str] = ["q"]
    xobjects: dict[str, int] = {}
    ext_gstates: dict[str, int] = {}
    y = layout.height - layout.top

    for block_index, block in enumerate(page_data.get("blocks", [])):
        block_type = block.get("type", "paragraph")

        if block_type in {"heading", "paragraph"}:
            text_ops, y, evidence = build_text_block(
                block,
                layout,
                y,
                page_number=page_number,
                block_index=block_index,
                escape_text=_escape_pdf_string,
            )
            ops.extend(text_ops)
            created_text_blocks.extend(evidence)

        elif block_type == "table":
            structures["table"] = True
            ops.append("%DS-BLOCK:table")
            table = block.get("table")
            if table and "rows" in table:
                row_height = 20.0
                col_width = layout.content_width / max(len(table["rows"][0]["cells"]), 1)
                for r_idx, row in enumerate(table["rows"]):
                    row_y = y - r_idx * row_height
                    # Draw row borders
                    ops.append(f"{pdf_number(layout.left)} {pdf_number(row_y)} m")
                    ops.append(
                        f"{pdf_number(layout.left + col_width * len(row['cells']))} "
                        f"{pdf_number(row_y)} l"
                    )
                    ops.append("S")
                    for c_idx, cell in enumerate(row["cells"]):
                        col_x = layout.left + c_idx * col_width
                        if cell is not None:
                            ops.append("BT")
                            ops.append("/F1 10 Tf")
                            ops.append(
                                f"1 0 0 1 {pdf_number(col_x + 2)} "
                                f"{pdf_number(row_y - 12)} Tm"
                            )
                            ops.append(f"({_escape_pdf_string(str(cell))}) Tj")
                            ops.append("ET")
                y -= len(table["rows"]) * row_height + 10.0

        elif block_type == "image":
            structures["image"] = True
            image = block["image"]
            asset = load_image_asset(image)
            resource_name = f"Im{len(xobjects) + 1}"
            image_object = _embed_image(writer, asset, image.get("alt"))
            xobjects[resource_name] = image_object
            placement = _image_placement(image, asset, left=layout.left, top=y)
            ops.append("%DS-BLOCK:image")
            ops.append("q")
            if image["fit"] == "cover":
                box = placement["box"]
                ops.append(f"{box[0]} {box[1]} {box[2]} {box[3]} re W n")
            draw = placement["draw"]
            ops.append(
                f"{draw[2]} 0 0 {draw[3]} {draw[0]} {draw[1]} cm /{resource_name} Do"
            )
            ops.append("Q")
            created_images.append({
                "page": page_number,
                "block_index": block_index,
                "resolved_path": str(asset.path),
                "asset_sha256": asset.sha256,
                "asset_bytes": asset.byte_count,
                "content_type": asset.content_type,
                "source_width": asset.width,
                "source_height": asset.height,
                "image_object": image_object,
                "bbox": placement["visible_bbox"],
                "transcoded": asset.transcoded,
            })
            y -= image["height"] + 20.0

        elif block_type == "vector_shape":
            structures["vector_shape"] = True
            ops.append("%DS-BLOCK:vector_shape")
            shape = {
                **block["shape"],
                "opacity": block["shape"].get("opacity", 1.0),
                "dash": block["shape"].get("dash", []),
            }
            graphics_name = f"GS{len(ext_gstates) + 1}"
            ext_gstates[graphics_name] = writer.add_object(
                (
                    f"<< /Type /ExtGState /ca {pdf_number(shape['opacity'])} "
                    f"/CA {pdf_number(shape['opacity'])} >>"
                ).encode("ascii")
            )
            ops.extend(shape_style_operators(shape, graphics_name))
            ops.extend(shape_path(shape))
            ops.extend([shape_paint_operator(shape), "Q"])
            created_shapes.append(
                shape_evidence(
                    shape,
                    page_number=page_number,
                    block_index=block_index,
                )
            )

    ops.append("Q")
    return "\n".join(ops), xobjects, ext_gstates


def _embed_image(writer: _PdfWriter, asset: ImageAsset, alt: str | None) -> int:
    soft_mask_object = None
    if asset.alpha_data is not None:
        soft_mask_object = writer.add_stream_object(
            soft_mask_dictionary(asset),
            asset.alpha_data,
        )
    dictionary = image_xobject_dictionary(
        asset,
        stream_length=len(asset.image_data),
        soft_mask_object=soft_mask_object,
        alt=alt,
    )
    return writer.add_stream_object(dictionary, asset.image_data)


def _image_placement(
    image: dict[str, Any],
    asset: ImageAsset,
    *,
    left: float,
    top: float,
) -> dict[str, list[float]]:
    box_width = image["width"]
    box_height = image["height"]
    box_bottom = top - box_height
    if image["fit"] == "stretch":
        draw_width = box_width
        draw_height = box_height
    else:
        scale_x = box_width / asset.width
        scale_y = box_height / asset.height
        scale = min(scale_x, scale_y) if image["fit"] == "contain" else max(scale_x, scale_y)
        draw_width = asset.width * scale
        draw_height = asset.height * scale
    draw_left = left + (box_width - draw_width) / 2.0
    draw_bottom = box_bottom + (box_height - draw_height) / 2.0
    box = [left, box_bottom, box_width, box_height]
    draw = [draw_left, draw_bottom, draw_width, draw_height]
    if image["fit"] == "contain":
        visible_bbox = [
            draw_left,
            draw_bottom,
            draw_left + draw_width,
            draw_bottom + draw_height,
        ]
    else:
        visible_bbox = [left, box_bottom, left + box_width, top]
    return {
        "box": _round_values(box),
        "draw": _round_values(draw),
        "visible_bbox": _round_values(visible_bbox),
    }


def _round_values(values: list[float]) -> list[float]:
    return [round(value, 4) for value in values]


def _escape_pdf_string(text: str) -> str:
    """Escape a string for safe inclusion in a PDF literal string."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
