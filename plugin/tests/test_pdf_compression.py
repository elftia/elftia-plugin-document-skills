"""Public balanced/aggressive PDF image-compression tests."""

import hashlib
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from document_skills_core.formats.pdf.create import create_pdf
from tests.test_pdf_public import _public, _request


def _photographic_png(path: Path) -> Path:
    luminance = Image.effect_noise((1_600, 1_200), 30).convert("L")
    green = luminance.point(lambda value: min(255, int(value * 0.9 + 12)))
    blue = luminance.point(lambda value: min(255, int(value * 0.75 + 28)))
    image = Image.merge("RGB", (luminance, green, blue))
    image.save(path, format="PNG", optimize=False)
    return path


def _image_pdf(path: Path, image: Path) -> Path:
    create_pdf(
        path,
        {
            "metadata": {
                "title": "Compression fixture",
                "author": "Elftia",
                "subject": "Image quality evidence",
            },
            "page_size": "A4",
            "pages": [{
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "Image compression semantic anchor",
                        "style": None,
                        "table": None,
                        "image": None,
                        "shape": None,
                    },
                    {
                        "type": "image",
                        "text": None,
                        "style": None,
                        "table": None,
                        "image": {
                            "filename": str(image),
                            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                            "content_type": "image/png",
                            "fit": "contain",
                            "width": 420.0,
                            "height": 315.0,
                            "alt": "Photographic compression fixture",
                        },
                        "shape": None,
                    },
                ],
                "metadata": None,
            }],
        },
    )
    return path


def test_public_balanced_and_aggressive_compression_have_visual_evidence(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = _photographic_png(tmp_path / "photographic.png")
    source = _image_pdf(tmp_path / "image-source.pdf", image)
    source_bytes = source.read_bytes()
    source_text = PdfReader(source).pages[0].extract_text()
    results: dict[str, tuple[Path, dict[str, object]]] = {}

    for mode in ("balanced", "aggressive"):
        output = tmp_path / f"compressed-{mode}.pdf"
        request = _request(
            tmp_path,
            f"compress-{mode}.json",
            {
                "schema_version": "1.0",
                "operation": "pdf.compress",
                "input": str(source),
                "output": str(output),
                "arguments": {"mode": mode},
            },
        )
        result = _public(
            project_root,
            "run",
            "--request",
            str(request),
            check=False,
        )
        assert result["status"] == "success", result
        results[mode] = (output, result)

    assert source.read_bytes() == source_bytes
    balanced_output, balanced_result = results["balanced"]
    aggressive_output, aggressive_result = results["aggressive"]
    assert balanced_output.stat().st_size < source.stat().st_size
    assert aggressive_output.stat().st_size < balanced_output.stat().st_size

    for mode, (output, result) in results.items():
        reader = PdfReader(output)
        assert reader.pages[0].extract_text() == source_text
        assert len(reader.pages[0].images) == 1
        operation = result["diagnostics"]["operation_result"]
        compression = operation["compression"]
        visual = operation["visual_diff"]
        assert compression["mode"] == mode
        assert compression["verified"] is True
        assert compression["images_recompressed"] == 1
        assert visual["source"] == "decoded-image-xobject-diff"
        assert visual["page_rendered"] is False
        assert visual["images"][0]["psnr_db"] >= visual["minimum_psnr_db"]
        gate_ids = {gate["id"] for gate in result["validation"]["gates"]}
        assert "visual.image-xobject-diff" in gate_ids

    assert balanced_result["diagnostics"]["operation_result"]["compression"][
        "images_downsampled"
    ] == 0
    assert aggressive_result["diagnostics"]["operation_result"]["compression"][
        "images_downsampled"
    ] == 1
