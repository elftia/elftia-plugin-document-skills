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
from .create_mapping import build_creation_mapping
from .create_document import document_text, paginate_document_pages
from .create_image_structure import (
    finalize_image_structure,
    page_struct_parent,
    split_image_evidence,
)
from .create_images import build_created_image
from .create_text_utils import needs_unicode_shaping, pdf_text_string
from .design_tokens import default_design_tokens
from .metadata_xmp import build_xmp
from .font_assets import load_font_assets
from .font_embedding import EmbeddedFontSet
from .font_shaping import TextShaper
from .table_layout import build_table_block
from .unicode_text import build_shaped_text_block


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

    def reserve_object(self) -> int:
        """Reserve a stable object number for deferred content."""
        return self.add_object(b"")

    def replace_object(self, obj_num: int, content: bytes) -> None:
        """Fill a previously reserved object exactly once by number."""
        for index, (number, generation, existing) in enumerate(self.objects):
            if number != obj_num:
                continue
            if existing:
                raise ValueError(f"PDF object {obj_num} is already populated")
            self.objects[index] = (number, generation, content)
            return
        raise ValueError(f"PDF object {obj_num} was not reserved")

    def add_stream_object(self, dictionary: bytes, stream_data: bytes) -> int:
        content = dictionary + b"\nstream\n" + stream_data + b"\nendstream"
        return self.add_object(content)

    def build(self, info_object: int) -> bytes:
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
            f"trailer\n<< /Size {max_obj + 1} /Root 1 0 R /Info {info_object} 0 R >>\n".encode("ascii")
        )
        xref.extend(f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
        return header + bytes(body) + bytes(xref)


def create_pdf(output: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Create a styled PDF document at the output path.

    Returns a creation result dict with page count, structures, and evidence.
    """
    metadata = document["metadata"]
    page_size = document["page_size"]
    requested_pages = document["pages"]
    design_tokens = document.get("design_tokens") or default_design_tokens()

    font_assets = load_font_assets(
        document.get("fonts", []),
        document_text(document),
    )
    text_shaper = TextShaper(font_assets)
    pages_data = paginate_document_pages(
        requested_pages,
        page_size,
        text_shaper,
        design_tokens["spacing"],
    )

    writer = _PdfWriter()

    catalog_obj = writer.reserve_object()
    pages_obj = writer.reserve_object()

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
    embedded_fonts = EmbeddedFontSet(writer, font_assets)

    page_object_nums: list[int] = []
    content_stream_nums: list[int] = []
    structures: dict[str, bool] = {
        "pages": True,
        "table": False,
        "image": False,
        "vector_shape": False,
        "metadata": True,
        "embedded_font": bool(font_assets),
    }
    created_images: list[dict[str, Any]] = []
    created_shapes: list[dict[str, Any]] = []
    created_text_blocks: list[dict[str, Any]] = []
    created_tables: list[dict[str, Any]] = []
    page_sizes: list[list[float]] = []
    content_boxes: list[list[float]] = []

    for page_idx, page_data in enumerate(pages_data):
        layout = resolve_page_layout(page_size, page_data)
        page_sizes.append([layout.width, layout.height])
        content_boxes.append(layout.content_bbox)
        struct_parent = page_struct_parent(page_data, page_idx)
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
            text_shaper,
            embedded_fonts,
            created_tables,
            design_tokens["spacing"],
            struct_parent,
        )
        content_bytes = operators.encode("latin-1", errors="strict")
        # Content stream object
        content_num = writer.add_stream_object(
            b"<< /Length " + str(len(content_bytes)).encode("ascii") + b" >>",
            content_bytes,
        )
        content_stream_nums.append(content_num)
        # Font dictionary
        font_dict = (
            f"<< /F1 {font_regular} 0 R /F2 {font_bold} 0 R "
            f"/F3 {font_italic} 0 R /F4 {font_bold_italic} 0 R"
            + (f" {embedded_fonts.page_resource_entries()}" if font_assets else "")
            + " >>"
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
            + (
                f"/StructParents {struct_parent} ".encode("ascii")
                if struct_parent is not None
                else b""
            )
            + b"/Resources << /Font " + font_dict + xobject_dict + ext_gstate_dict + b" >> >>"
        )
        page_object_nums.append(page_num)

    # Kids array for Pages
    kids = " ".join(f"{n} 0 R" for n in page_object_nums)
    pages_content = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_nums)} >>"
    ).encode("ascii")

    embedded_fonts.finalize(writer)
    structure_root = finalize_image_structure(
        writer,
        created_images,
        page_object_nums,
    )

    # Info dictionary. Unicode values use deterministic UTF-16BE hex strings.
    title = pdf_text_string(metadata.get("title", ""))
    author = pdf_text_string(metadata.get("author", ""))
    subject = pdf_text_string(metadata.get("subject", ""))
    info_content = (
        f"<< /Title {title} /Author {author} /Subject {subject} "
        f"/Creator (Elftia Document Skills) /Producer (Elftia PDF Core) "
        f"/CreationDate (D:20260101000000+00'00') >>"
    ).encode("ascii")
    info_object = writer.add_object(info_content)
    xmp_metadata = {
        "title": metadata.get("title", ""),
        "author": metadata.get("author", ""),
        "subject": metadata.get("subject", ""),
        "keywords": "",
    }
    xmp_bytes = build_xmp(xmp_metadata)
    xmp_object = writer.add_stream_object(
        (
            f"<< /Type /Metadata /Subtype /XML /Length {len(xmp_bytes)} >>"
        ).encode("ascii"),
        xmp_bytes,
    )

    # Now build the catalog + pages in the correct position
    # Rebuild objects with catalog at obj 1 and pages at obj 2
    writer.replace_object(
        catalog_obj,
        (
            f"<< /Type /Catalog /Pages {pages_obj} 0 R "
            f"/Metadata {xmp_object} 0 R"
            + (
                f" /MarkInfo << /Marked true >> /StructTreeRoot {structure_root} 0 R"
                if structure_root is not None
                else ""
            )
            + " >>"
        ).encode("ascii"),
    )
    writer.replace_object(pages_obj, pages_content)

    pdf_bytes = writer.build(info_object)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pdf_bytes)

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    mapping = build_creation_mapping(
        pages_data,
        page_object_nums,
        content_stream_nums,
        page_sizes,
        text_blocks=created_text_blocks,
        images=created_images,
        tables=created_tables,
        shapes=created_shapes,
    )
    public_images, image_structure = split_image_evidence(created_images)

    return {
        "page_count": len(page_object_nums),
        "page_size": page_sizes[0],
        "page_sizes": page_sizes,
        "content_boxes": content_boxes,
        "structures": structures,
        "images": public_images,
        "image_structure": image_structure,
        "fonts": embedded_fonts.evidence(),
        "shapes": created_shapes,
        "tables": created_tables,
        "text_blocks": created_text_blocks,
        "design_tokens": design_tokens,
        "mapping": mapping,
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
    text_shaper: TextShaper,
    embedded_fonts: EmbeddedFontSet,
    created_tables: list[dict[str, Any]],
    spacing: dict[str, float],
    struct_parent: int | None,
) -> tuple[str, dict[str, int], dict[str, int]]:
    """Build content stream operators for a page."""
    ops: list[str] = ["q"]
    xobjects: dict[str, int] = {}
    ext_gstates: dict[str, int] = {}
    next_mcid = 0
    y = layout.height - layout.top

    for block_index, block in enumerate(page_data.get("blocks", [])):
        block_type = block.get("type", "paragraph")

        if block_type in {"heading", "paragraph"}:
            if needs_unicode_shaping(block):
                text_ops, y, evidence = build_shaped_text_block(
                    block,
                    layout,
                    y,
                    page_number=page_number,
                    block_index=block_index,
                    shaper=text_shaper,
                    fonts=embedded_fonts,
                    spacing_after=spacing[f"{block_type}_gap"],
                )
            else:
                text_ops, y, evidence = build_text_block(
                    block,
                    layout,
                    y,
                    page_number=page_number,
                    block_index=block_index,
                    escape_text=_escape_pdf_string,
                    spacing_after=spacing[f"{block_type}_gap"],
                )
            ops.extend(text_ops)
            created_text_blocks.extend(evidence)

        elif block_type == "table":
            structures["table"] = True
            table_ops, y, table_evidence = build_table_block(
                block,
                layout,
                y,
                page_number=page_number,
                block_index=block_index,
                shaper=text_shaper,
                fonts=embedded_fonts,
                spacing_after=spacing["table_gap"],
            )
            ops.extend(table_ops)
            created_tables.append(table_evidence)

        elif block_type == "image":
            structures["image"] = True
            image = block["image"]
            resource_name = f"Im{len(xobjects) + 1}"
            alt = image.get("alt")
            mcid = next_mcid if alt else None
            if mcid is not None:
                next_mcid += 1
            image_ops, image_object, image_evidence = build_created_image(
                writer,
                image,
                page_number=page_number,
                block_index=block_index,
                resource_name=resource_name,
                left=layout.left,
                top=y,
                mcid=mcid,
                struct_parent=struct_parent,
            )
            xobjects[resource_name] = image_object
            ops.extend(image_ops)
            created_images.append(image_evidence)
            y -= image["height"] + spacing["image_gap"]

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


def _escape_pdf_string(text: str) -> str:
    """Escape a string for safe inclusion in a PDF literal string."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
