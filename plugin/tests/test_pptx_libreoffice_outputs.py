"""LibreOffice-backed public PPTX render and PDF conversion tests."""

from hashlib import sha256
import json
from pathlib import Path
import struct
import zipfile
import zlib

from document_skills_core.core.capabilities import (
    DetectionEvidence,
    ProviderCatalog,
)
from document_skills_core.core.capabilities.reports import build_capabilities
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.validation import reopen_pdf
from document_skills_core.formats.pptx.render_validation import validate_render_bundle
from document_skills_core.providers.libreoffice import build_libreoffice_provider


class _CallableDetector:
    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(True, version="25.8.0", path="/fake/soffice")


class _AbsentDetector:
    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(False, reason="LibreOffice is absent")


class _RenderRunner:
    def __init__(self, *, pdf_pages: int | None = None) -> None:
        self.pdf_pages = pdf_pages
        self.calls: list[dict[str, object]] = []

    def set_executable(self, _executable: str) -> None:
        pass

    def convert(
        self,
        input_path: Path,
        target_format: str,
        output_dir: Path,
        *,
        timeout_seconds: float | None = None,
    ) -> Path:
        self.calls.append({
            "format": target_format,
            "input": str(input_path),
            "timeout": timeout_seconds,
        })
        output = output_dir / f"{input_path.stem}.{target_format}"
        if target_format == "pdf":
            from pptx import Presentation

            pages = self.pdf_pages
            if pages is None:
                pages = len(Presentation(input_path).slides)
            _write_pdf(output, pages)
        elif target_format == "png":
            from pptx import Presentation

            presentation = Presentation(input_path)
            assert len(presentation.slides) == 1
            self.calls[-1]["title"] = presentation.slides[0].shapes.title.text
            output.write_bytes(_png(4, 3, (40, 80, 120, 255)))
        else:  # pragma: no cover - operation contract
            raise AssertionError(target_format)
        return output


class _TimeoutRunner:
    def set_executable(self, _executable: str) -> None:
        pass

    def convert(self, *_args, **_kwargs) -> Path:
        raise DocumentSkillsError(
            ErrorCode.PROCESS_TIMEOUT,
            "LibreOffice timed out.",
        )


def test_pptx_convert_pdf_promotes_reopened_page_matched_output(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _deck(tmp_path / "source.pptx", slides=2)
    source_hash = sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "converted.pdf"
    definition, provider = build_libreoffice_provider(
        project_root,
        detector=_CallableDetector(),
        runner=_RenderRunner(),
    )

    result = provider.execute("pptx.convert.pdf", _request(
        "pptx.convert.pdf",
        source,
        output,
    ))

    assert result["status"] == "success", result
    assert reopen_pdf(output)["pages"] == 2
    assert sha256(source.read_bytes()).hexdigest() == source_hash
    outcomes = {gate["id"]: gate["outcome"] for gate in result["validation"]["gates"]}
    assert outcomes["operation.pptx-source-deep-validation"] == "pass"
    assert outcomes["operation.pptx-pdf-page-count"] == "pass"
    assert {item.operation for item in definition.capabilities} >= {
        "pptx.convert.pdf",
        "pptx.render",
    }
    assert callable(definition.validators["visual"])


def test_pptx_libreoffice_profile_capability_truth(
    project_root: Path,
) -> None:
    for detector, expected in [(_CallableDetector(), True), (_AbsentDetector(), False)]:
        definition, _provider = build_libreoffice_provider(
            project_root,
            detector=detector,
            runner=_RenderRunner(),
        )
        registry = ProviderCatalog()
        registry.register_provider(definition)
        report = build_capabilities(project_root, "pptx", registry)
        operations = {
            item["operation"]: item
            for item in report["operations"]
        }
        assert operations["pptx.convert.pdf"]["available"] is expected
        assert operations["pptx.render"]["available"] is expected
        assert report["validation"]["visual"] == (
            "available" if expected else "unavailable"
        )


def test_pptx_render_promotes_pdf_and_every_slide_png_bundle(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _deck(tmp_path / "source.pptx", slides=2)
    output = tmp_path / "render.zip"
    runner = _RenderRunner()
    _definition, provider = build_libreoffice_provider(
        project_root,
        detector=_CallableDetector(),
        runner=runner,
    )

    result = provider.execute("pptx.render", _request("pptx.render", source, output))

    assert result["status"] == "success", result
    assert [item["format"] for item in runner.calls] == ["pdf", "png", "png"]
    assert [item.get("title") for item in runner.calls[1:]] == ["Slide 1", "Slide 2"]
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "deck.pdf",
            "manifest.json",
            "slides/slide-001.png",
            "slides/slide-002.png",
        }
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["slides"] == 2
    assert manifest["pdf"]["pages"] == 2
    assert [item["slide"] for item in manifest["images"]] == [1, 2]
    visual = next(
        gate for gate in result["validation"]["gates"]
        if gate["id"] == "visual.render"
    )
    assert visual["required"] is True
    assert visual["outcome"] == "pass"
    assert visual["evidence"]["slides_rendered"] == 2


def test_pptx_convert_pdf_rejects_page_count_mismatch_without_output(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _deck(tmp_path / "source.pptx", slides=2)
    source_hash = sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "prior-output.pdf"
    prior_output = b"prior destination"
    output.write_bytes(prior_output)
    _definition, provider = build_libreoffice_provider(
        project_root,
        detector=_CallableDetector(),
        runner=_RenderRunner(pdf_pages=1),
    )

    result = provider.execute("pptx.convert.pdf", _request(
        "pptx.convert.pdf",
        source,
        output,
    ))

    assert result["status"] == "failed"
    assert output.read_bytes() == prior_output
    assert sha256(source.read_bytes()).hexdigest() == source_hash


def test_pptx_render_timeout_preserves_source_and_publishes_nothing(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _deck(tmp_path / "source.pptx", slides=1)
    source_hash = sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "must-not-exist.zip"
    _definition, provider = build_libreoffice_provider(
        project_root,
        detector=_CallableDetector(),
        runner=_TimeoutRunner(),
    )

    result = provider.execute("pptx.render", _request("pptx.render", source, output))

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == ErrorCode.PROCESS_TIMEOUT.value
    assert not output.exists()
    assert sha256(source.read_bytes()).hexdigest() == source_hash


def test_render_bundle_validator_rejects_manifest_byte_mismatch(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _deck(tmp_path / "source.pptx", slides=1)
    output = tmp_path / "render.zip"
    _definition, provider = build_libreoffice_provider(
        project_root,
        detector=_CallableDetector(),
        runner=_RenderRunner(),
    )
    result = provider.execute("pptx.render", _request("pptx.render", source, output))
    assert result["status"] == "success"
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    manifest["images"][0]["bytes"] += 1

    try:
        validate_render_bundle(output, manifest)
    except DocumentSkillsError as error:
        assert error.code == ErrorCode.VALIDATION_FAILED
    else:  # pragma: no cover - negative assertion
        raise AssertionError("tampered render manifest was accepted")


def _request(operation: str, source: Path, output: Path) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": operation,
        "input": str(source),
        "output": str(output),
        "arguments": {},
        "options": {"fidelity": "enhanced"},
    }


def _deck(path: Path, *, slides: int) -> Path:
    from pptx import Presentation

    presentation = Presentation()
    for number in range(1, slides + 1):
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = f"Slide {number}"
        slide.placeholders[1].text = "Body"
    presentation.save(path)
    return path


def _write_pdf(path: Path, pages: int) -> None:
    import fitz

    document = fitz.open()
    for number in range(1, pages + 1):
        page = document.new_page(width=800, height=600)
        page.insert_text((72, 72), f"Slide {number}")
    document.save(path)
    document.close()


def _png(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgba) * width for _row in range(height))
    return b"\x89PNG\r\n\x1a\n" + b"".join([
        _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
        _chunk(b"IDAT", zlib.compress(raw)),
        _chunk(b"IEND", b""),
    ])


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )
