"""Executable-free coverage for the optional Poppler/Tesseract provider."""

from io import BytesIO
import json
from pathlib import Path
import zipfile

from PIL import Image
import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.process import ProcessResult
from document_skills_core.formats.pdf.optional_provider_contracts import (
    parse_optional_provider_arguments,
)
from document_skills_core.providers.pdf_tools import ocr as ocr_module
from document_skills_core.providers.pdf_tools import service as service_module
from document_skills_core.providers.pdf_tools.archive import manifest_bytes, write_archive
from document_skills_core.providers.pdf_tools.deadline import OperationDeadline
from document_skills_core.providers.pdf_tools.detector import PdfToolDetector
from document_skills_core.providers.pdf_tools.ocr import ocr_pdf
from document_skills_core.providers.pdf_tools.pdf_input import safe_selected_pages
from document_skills_core.providers.pdf_tools.render import render_pdf
from document_skills_core.providers.pdf_tools.runner import PdfToolRunner
from document_skills_core.providers.pdf_tools.service import PdfToolService


class ProbeRunner:
    def __init__(
        self,
        *,
        poppler_version: str = "25.1.0",
        tesseract_version: str = "5.5.0",
        languages: tuple[str, ...] = ("eng", "osd"),
    ) -> None:
        self.poppler_version = poppler_version
        self.tesseract_version = tesseract_version
        self.languages = languages

    def run(self, _provider, executable, arguments, **_kwargs):
        name = Path(executable).stem
        if name == "pdftoppm":
            return ProcessResult(
                0,
                "",
                f"pdftoppm version {self.poppler_version}",
                1,
            )
        if arguments == ["--version"]:
            return ProcessResult(0, f"tesseract {self.tesseract_version}\n", "", 1)
        language_lines = "\n".join(self.languages)
        return ProcessResult(
            0,
            f"List of available languages ({len(self.languages)}):\n{language_lines}\n",
            "",
            1,
        )


class CapturingRenderProcessRunner:
    def __init__(self) -> None:
        self.arguments: list[str] | None = None

    def run(self, _provider, _executable, arguments, **_kwargs):
        self.arguments = list(arguments)
        Path(arguments[-1]).with_suffix(".png").write_bytes(_png())
        return ProcessResult(0, "", "", 1)


class FakePdfRunner:
    def __init__(
        self,
        *,
        image_payload: bytes | None = None,
        tsv: str | None = None,
        advance=None,
    ) -> None:
        self.image_payload = image_payload or _png()
        self.tsv = tsv or _valid_tsv()
        self.advance = advance or (lambda: None)
        self.languages = frozenset()
        self.render_calls = 0
        self.ocr_calls = 0

    def configure(self, _paths, *, languages=frozenset()):
        self.languages = languages

    def require_languages(self, languages):
        missing = set(languages) - self.languages
        if missing:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "missing language",
                status="unavailable",
            )

    def render_page(self, _source, output_prefix, *, output_format, **_kwargs):
        self.render_calls += 1
        suffix = ".png" if output_format == "png" else ".jpg"
        rendered = output_prefix.with_suffix(suffix)
        rendered.write_bytes(self.image_payload)
        self.advance()
        return rendered

    def ocr_tsv(self, _image, **_kwargs):
        self.ocr_calls += 1
        self.advance()
        return self.tsv


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_detector_accepts_supported_versions_and_required_language(
    project_root: Path,
    tmp_path: Path,
) -> None:
    detector = _detector(project_root, tmp_path, ProbeRunner())

    evidence = detector.detect()

    assert evidence.available is True
    assert detector.accepted_languages() == frozenset({"eng", "osd"})
    diagnostics = detector.diagnostics()
    assert diagnostics["executable_versions"] == {
        "pdftoppm": "25.1.0",
        "tesseract": "5.5.0",
    }
    assert diagnostics["tesseract_languages"] == ["eng", "osd"]


@pytest.mark.parametrize(
    ("runner", "reason"),
    [
        (ProbeRunner(poppler_version="22.12.0"), "supported range"),
        (ProbeRunner(tesseract_version="6.0.0"), "supported range"),
        (ProbeRunner(languages=("deu", "osd")), "lacks the required eng"),
    ],
)
def test_detector_rejects_unsupported_runtime_evidence(
    project_root: Path,
    tmp_path: Path,
    runner: ProbeRunner,
    reason: str,
) -> None:
    evidence = _detector(project_root, tmp_path, runner).detect()

    assert evidence.available is False
    assert reason in (evidence.reason or "")


def test_runner_rejects_unprobed_ocr_language(
    project_root: Path,
    tmp_path: Path,
) -> None:
    runner = PdfToolRunner(project_root)
    executable = tmp_path / "tesseract.exe"
    executable.touch()
    runner.configure(
        {"tesseract": executable},
        languages=frozenset({"eng"}),
    )

    with pytest.raises(DocumentSkillsError) as caught:
        runner.require_languages(["eng", "jpn"])

    assert caught.value.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert caught.value.details["missing_languages"] == ["jpn"]


def test_runner_renders_the_crop_box_with_stable_poppler_argument_order(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _minimal_pdf(tmp_path / "source.pdf")
    executable = tmp_path / "pdftoppm.exe"
    executable.touch()
    process_runner = CapturingRenderProcessRunner()
    runner = PdfToolRunner(project_root, process_runner=process_runner)
    runner.configure({"pdftoppm": executable})
    output_prefix = tmp_path / "rendered"

    rendered = runner.render_page(
        source,
        output_prefix,
        page=1,
        dpi=72,
        output_format="png",
        max_output_bytes=1_000_000,
    )

    assert rendered == output_prefix.with_suffix(".png")
    assert process_runner.arguments == [
        "-f",
        "1",
        "-l",
        "1",
        "-r",
        "72",
        "-singlefile",
        "-png",
        "-cropbox",
        str(source.resolve()),
        str(output_prefix.resolve()),
    ]


def test_optional_provider_contract_numeric_defaults_and_inclusive_maxima() -> None:
    render = parse_optional_provider_arguments("pdf.render", {})
    ocr = parse_optional_provider_arguments("pdf.ocr", {})

    assert (render["dpi"], render["max_pixels"], render["max_total_bytes"]) == (
        144,
        40_000_000,
        64 * 1024 * 1024,
    )
    assert (
        ocr["dpi"],
        ocr["max_pixels"],
        ocr["max_total_bytes"],
        ocr["languages"],
    ) == (300, 40_000_000, 64 * 1024 * 1024, ["eng"])
    assert ocr["skip_text_pages"] is True
    assert parse_optional_provider_arguments(
        "pdf.render",
        {
            "dpi": 36,
            "max_pixels": 100_000_000,
            "max_total_bytes": 128 * 1024 * 1024,
        },
    )["dpi"] == 36
    assert parse_optional_provider_arguments("pdf.render", {"dpi": 300})["dpi"] == 300
    assert parse_optional_provider_arguments("pdf.ocr", {"dpi": 72})["dpi"] == 72
    assert parse_optional_provider_arguments("pdf.ocr", {"dpi": 300})["dpi"] == 300


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("pdf.render", {"dpi": 35}),
        ("pdf.render", {"dpi": 301}),
        ("pdf.ocr", {"dpi": 71}),
        ("pdf.ocr", {"dpi": 301}),
        ("pdf.render", {"max_pixels": 100_000_001}),
        ("pdf.ocr", {"max_total_bytes": 128 * 1024 * 1024 + 1}),
    ],
)
def test_optional_provider_contract_rejects_values_above_or_below_bounds(
    operation: str,
    arguments: dict[str, int],
) -> None:
    with pytest.raises(DocumentSkillsError) as caught:
        parse_optional_provider_arguments(operation, arguments)

    assert caught.value.code == ErrorCode.REQUEST_INVALID


def test_render_rejects_a_cumulative_pixel_estimate_above_the_selected_limit(
    tmp_path: Path,
) -> None:
    source = _minimal_pdf(tmp_path / "pixel-budget.pdf")
    output = tmp_path / "render.zip"
    arguments = _render_arguments()
    arguments["max_pixels"] = 9_999

    with pytest.raises(DocumentSkillsError) as caught:
        render_pdf(
            source,
            output,
            arguments,
            private_root=tmp_path,
            runner=FakePdfRunner(),
            deadline=OperationDeadline(10.0),
        )

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert not output.exists()


def test_ocr_language_count_and_word_count_are_bounded(monkeypatch) -> None:
    eight_languages = [f"l{index:02d}" for index in range(8)]
    parsed = parse_optional_provider_arguments(
        "pdf.ocr",
        {"languages": list(reversed(eight_languages))},
    )
    assert parsed["languages"] == eight_languages
    with pytest.raises(DocumentSkillsError) as caught:
        parse_optional_provider_arguments(
            "pdf.ocr",
            {"languages": [*eight_languages, "l08"]},
        )
    assert caught.value.code == ErrorCode.REQUEST_INVALID

    assert ocr_module.MAX_OCR_WORDS_PER_PAGE == 100_000
    monkeypatch.setattr(ocr_module, "MAX_OCR_WORDS_PER_PAGE", 1)
    with pytest.raises(DocumentSkillsError) as caught:
        ocr_module._parse_tsv(
            "level\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t0\t0\t1\t1\t90\tone\n"
            "5\t1\t0\t1\t1\t90\ttwo\n",
            raster_width=100,
            raster_height=100,
        )
    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE


def test_render_and_ocr_execute_with_fake_tools(tmp_path: Path) -> None:
    source = _minimal_pdf(tmp_path / "source.pdf")
    runner = FakePdfRunner()

    render_output = tmp_path / "render.zip"
    render_result, _manifest, _records = render_pdf(
        source,
        render_output,
        _render_arguments(),
        private_root=tmp_path,
        runner=runner,
        deadline=OperationDeadline(10.0),
    )
    assert render_result["render"]["page_count"] == 1
    assert render_output.is_file()

    ocr_output = tmp_path / "ocr.zip"
    ocr_result, _manifest, _records = ocr_pdf(
        source,
        ocr_output,
        _ocr_arguments(),
        private_root=tmp_path,
        runner=runner,
        deadline=OperationDeadline(10.0),
    )
    assert ocr_result["ocr"]["ocr_page_count"] == 1
    assert ocr_result["ocr"]["pages"][0]["word_count"] == 1
    assert ocr_output.is_file()


def test_full_service_promotes_fake_ocr_with_pdf_semantics(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _minimal_pdf(
        tmp_path / "ocr-source.pdf",
        crop_box=(10, 20, 90, 80),
        rotation=90,
    )
    output = tmp_path / "ocr.zip"
    service = _ocr_service(
        project_root,
        tmp_path,
        FakePdfRunner(image_payload=_png(width=60, height=80)),
    )

    result = service.execute("pdf.ocr", _ocr_request(source, output))

    assert result["status"] == "success", result["errors"]
    page = result["diagnostics"]["operation_result"]["ocr"]["pages"][0]
    assert page["semantics"] == {
        "media_box": [0.0, 0.0, 100.0, 100.0],
        "crop_box": [10.0, 20.0, 90.0, 80.0],
        "rotation": 90,
        "dpi": 72,
        "expected_raster": {"width": 60, "height": 80},
        "raster": {
            "width": 60,
            "height": 80,
            "bbox": [0, 0, 60, 80],
            "bounds": [0, 0, 60, 80],
            "bounded": True,
            "overflow": False,
        },
    }
    gates = {gate["id"]: gate for gate in result["validation"]["gates"]}
    assert gates["ocr.page-semantics"]["outcome"] == "pass"
    assert gates["ocr.page-semantics"]["evidence"] == {
        "dpi": 72,
        "languages": ["eng"],
        "pages": [1],
        "validated_sidecars": 1,
    }


def test_default_ocr_processes_image_bearing_page_with_small_embedded_text(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _mixed_image_text_pdf(tmp_path / "mixed.pdf")
    output = tmp_path / "mixed-ocr.zip"
    runner = FakePdfRunner()
    service = _ocr_service(project_root, tmp_path, runner)
    request = _ocr_request(source, output)
    request["arguments"].pop("skip_text_pages")

    result = service.execute("pdf.ocr", request)

    assert result["status"] == "success", result["errors"]
    assert runner.render_calls == 1
    assert runner.ocr_calls == 1
    ocr = result["diagnostics"]["operation_result"]["ocr"]
    assert ocr["provider"] == "poppler+tesseract"
    assert ocr["ocr_page_count"] == 1
    assert ocr["skipped_text_page_count"] == 0
    assert ocr["pages"][0]["status"] == "ocr_completed"
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "page-0001.json",
            "page-0001.txt",
        }
        sidecar = json.loads(archive.read("page-0001.json"))
        assert sidecar["status"] == "ocr_completed"
        assert sidecar["source"] == "tesseract"
        assert archive.read("page-0001.txt") == b"Hello\n"


def test_default_ocr_skips_only_sufficient_text_page_with_no_image_evidence(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _sufficient_text_pdf(tmp_path / "text-page.pdf")
    output = tmp_path / "text-page-ocr.zip"
    runner = FakePdfRunner()
    service = _ocr_service(project_root, tmp_path, runner)
    request = _ocr_request(source, output)
    request["arguments"].pop("skip_text_pages")

    result = service.execute("pdf.ocr", request)

    assert result["status"] == "success", result["errors"]
    assert runner.render_calls == 0
    assert runner.ocr_calls == 0
    ocr = result["diagnostics"]["operation_result"]["ocr"]
    assert ocr["provider"] == "poppler+tesseract"
    assert ocr["source"] == "not_run_existing_text"
    assert ocr["ocr_page_count"] == 0
    assert ocr["skipped_text_page_count"] == 1
    assert ocr["pages"][0]["status"] == "skipped_existing_text"
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"manifest.json", "page-0001.json"}
        sidecar = json.loads(archive.read("page-0001.json"))
        assert sidecar["status"] == "skipped_existing_text"
        assert sidecar["source"] == "embedded_text_detection"
        assert sidecar["skip_evidence"]["policy"] == (
            "sufficient_embedded_text_without_image_evidence"
        )


def test_explicit_skip_text_pages_false_ocr_processes_sufficient_text_page(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _sufficient_text_pdf(tmp_path / "forced-text-page.pdf")
    output = tmp_path / "forced-text-page-ocr.zip"
    runner = FakePdfRunner()
    service = _ocr_service(project_root, tmp_path, runner)

    result = service.execute("pdf.ocr", _ocr_request(source, output))

    assert result["status"] == "success", result["errors"]
    assert runner.render_calls == 1
    assert runner.ocr_calls == 1
    page = result["diagnostics"]["operation_result"]["ocr"]["pages"][0]
    assert page["status"] == "ocr_completed"
    with zipfile.ZipFile(output) as archive:
        assert "page-0001.txt" in archive.namelist()
    assert output.is_file()


def test_full_service_rejects_mismatched_ocr_extent_without_replacement(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _minimal_pdf(tmp_path / "ocr-source.pdf")
    output = tmp_path / "ocr.zip"
    output.write_bytes(b"existing")
    service = _ocr_service(
        project_root,
        tmp_path,
        FakePdfRunner(image_payload=_png(width=99, height=100)),
    )

    result = service.execute("pdf.ocr", _ocr_request(source, output))

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == ErrorCode.PROVIDER_FAILED.value
    assert output.read_bytes() == b"existing"


def test_full_service_rejects_ocr_bbox_outside_raster_without_replacement(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _minimal_pdf(tmp_path / "ocr-source.pdf")
    output = tmp_path / "ocr.zip"
    output.write_bytes(b"existing")
    overflowing_tsv = (
        "level\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t99\t10\t2\t5\t90\toverflow\n"
    )
    service = _ocr_service(
        project_root,
        tmp_path,
        FakePdfRunner(tsv=overflowing_tsv),
    )

    result = service.execute("pdf.ocr", _ocr_request(source, output))

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == ErrorCode.PROVIDER_FAILED.value
    assert output.read_bytes() == b"existing"


def test_ocr_semantic_gate_rejects_self_consistent_selected_page_tampering(
    project_root: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _minimal_pdf(tmp_path / "ocr-source.pdf")
    source_before = source.read_bytes()
    output = tmp_path / "ocr.zip"
    output.write_bytes(b"existing")
    real_ocr_pdf = service_module.ocr_pdf

    def tampered_ocr_pdf(*args, **kwargs):
        operation_result, manifest, records = real_ocr_pdf(*args, **kwargs)
        manifest["pages"][0]["page"] = 2
        staged = args[1]
        with zipfile.ZipFile(staged) as archive:
            payloads = {name: archive.read(name) for name in archive.namelist()}
        payloads["manifest.json"] = manifest_bytes(manifest)
        write_archive(staged, payloads)
        return operation_result, manifest, records

    monkeypatch.setattr(service_module, "ocr_pdf", tampered_ocr_pdf)
    service = _ocr_service(project_root, tmp_path, FakePdfRunner())

    result = service.execute("pdf.ocr", _ocr_request(source, output))

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == ErrorCode.VALIDATION_FAILED.value
    assert source.read_bytes() == source_before
    assert output.read_bytes() == b"existing"


def test_full_service_promotes_fake_render_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _minimal_pdf(
        tmp_path / "source.pdf",
        crop_box=(10, 20, 90, 80),
        rotation=90,
    )
    output = tmp_path / "render.zip"
    detector = _detector(
        project_root,
        tmp_path,
        ProbeRunner(),
        require_tesseract=False,
    )
    service = PdfToolService(
        project_root,
        operation="pdf.render",
        detector=detector,
        runner=FakePdfRunner(image_payload=_png(width=60, height=80)),
    )

    result = service.execute(
        "pdf.render",
        {
            "schema_version": "1.0",
            "operation": "pdf.render",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "pages": [1],
                "dpi": 72,
                "format": "png",
                "max_pixels": 1_000_000,
                "max_total_bytes": 1_000_000,
            },
        },
    )

    assert result["status"] == "success", result["errors"]
    page = result["diagnostics"]["operation_result"]["render"]["pages"][0]
    assert {
        key: page[key]
        for key in (
            "page",
            "media_box",
            "crop_box",
            "rotation",
            "dpi",
            "width",
            "height",
            "pixels",
            "raster_evidence",
        )
    } == {
        "page": 1,
        "media_box": [0.0, 0.0, 100.0, 100.0],
        "crop_box": [10.0, 20.0, 90.0, 80.0],
        "rotation": 90,
        "dpi": 72,
        "width": 60,
        "height": 80,
        "pixels": 4_800,
        "raster_evidence": {
            "expected_width": 60,
            "expected_height": 80,
            "bbox": [0, 0, 60, 80],
            "bounds": [0, 0, 60, 80],
            "bounded": True,
            "overflow": False,
        },
    }
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["pages"][0] == page
    assert output.is_file()


def test_full_service_rejects_mismatched_render_extent_without_replacement(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _minimal_pdf(tmp_path / "source.pdf")
    output = tmp_path / "render.zip"
    output.write_bytes(b"existing")
    detector = _detector(
        project_root,
        tmp_path,
        ProbeRunner(),
        require_tesseract=False,
    )
    service = PdfToolService(
        project_root,
        operation="pdf.render",
        detector=detector,
        runner=FakePdfRunner(image_payload=_png(width=99, height=100)),
    )

    result = service.execute(
        "pdf.render",
        {
            "schema_version": "1.0",
            "operation": "pdf.render",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "pages": [1],
                "dpi": 72,
                "format": "png",
                "max_pixels": 1_000_000,
                "max_total_bytes": 1_000_000,
            },
        },
    )

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == ErrorCode.PROVIDER_FAILED.value
    assert output.read_bytes() == b"existing"


def test_oversized_or_malformed_tool_output_does_not_replace_destination(
    tmp_path: Path,
) -> None:
    source = _minimal_pdf(tmp_path / "source.pdf")
    output = tmp_path / "sidecar.zip"
    output.write_bytes(b"existing")
    arguments = _render_arguments()
    arguments["max_total_bytes"] = 32

    with pytest.raises(DocumentSkillsError) as caught:
        render_pdf(
            source,
            output,
            arguments,
            private_root=tmp_path,
            runner=FakePdfRunner(),
            deadline=OperationDeadline(10.0),
        )

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert output.read_bytes() == b"existing"

    with pytest.raises(DocumentSkillsError) as caught:
        ocr_pdf(
            source,
            output,
            _ocr_arguments(),
            private_root=tmp_path,
            runner=FakePdfRunner(tsv="bad\theader\n"),
            deadline=OperationDeadline(10.0),
        )

    assert caught.value.code == ErrorCode.PROVIDER_FAILED
    assert output.read_bytes() == b"existing"


def test_whole_operation_deadline_stops_after_provider_call(tmp_path: Path) -> None:
    source = _minimal_pdf(tmp_path / "source.pdf")
    output = tmp_path / "render.zip"
    clock = FakeClock()
    deadline = OperationDeadline(2.0, clock=clock)
    runner = FakePdfRunner(advance=lambda: clock.advance(3.0))

    with pytest.raises(DocumentSkillsError) as caught:
        render_pdf(
            source,
            output,
            _render_arguments(),
            private_root=tmp_path,
            runner=runner,
            deadline=deadline,
        )

    assert caught.value.code == ErrorCode.PROCESS_TIMEOUT
    assert not output.exists()


def test_nondefault_user_unit_and_oversized_page_selections_fail_closed(
    tmp_path: Path,
) -> None:
    source = _minimal_pdf(tmp_path / "scaled.pdf", user_unit="2")
    with pytest.raises(DocumentSkillsError) as caught:
        safe_selected_pages(source, [1], max_selected_pages=1)
    assert caught.value.code == ErrorCode.ENHANCEMENT_REQUIRED

    with pytest.raises(DocumentSkillsError):
        parse_optional_provider_arguments(
            "pdf.render",
            {"pages": list(range(1, 258))},
        )
    with pytest.raises(DocumentSkillsError):
        parse_optional_provider_arguments(
            "pdf.ocr",
            {"pages": list(range(1, 66))},
        )


def _detector(
    project_root: Path,
    tmp_path: Path,
    runner: ProbeRunner,
    *,
    require_tesseract: bool = True,
) -> PdfToolDetector:
    paths = {
        name: str(tmp_path / f"{name}.exe")
        for name in ("pdftoppm", "tesseract")
    }
    return PdfToolDetector(
        project_root,
        require_tesseract=require_tesseract,
        path_finder=paths.get,
        process_runner=runner,
    )


def _ocr_service(
    project_root: Path,
    tmp_path: Path,
    runner: FakePdfRunner,
) -> PdfToolService:
    return PdfToolService(
        project_root,
        operation="pdf.ocr",
        detector=_detector(project_root, tmp_path, ProbeRunner()),
        runner=runner,
    )


def _ocr_request(source: Path, output: Path) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "pdf.ocr",
        "input": str(source),
        "output": str(output),
        "arguments": {
            "pages": [1],
            "dpi": 72,
            "languages": ["eng"],
            "skip_text_pages": False,
            "max_pixels": 1_000_000,
            "max_total_bytes": 1_000_000,
        },
    }


def _png(*, width: int = 100, height: int = 100) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _valid_tsv() -> str:
    return (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t1\t2\t3\t4\t96.5\tHello\n"
    )


def _render_arguments() -> dict[str, object]:
    return parse_optional_provider_arguments(
        "pdf.render",
        {
            "pages": [1],
            "dpi": 72,
            "format": "png",
            "max_pixels": 1_000_000,
            "max_total_bytes": 1_000_000,
        },
    )


def _ocr_arguments() -> dict[str, object]:
    return parse_optional_provider_arguments(
        "pdf.ocr",
        {
            "pages": [1],
            "dpi": 72,
            "languages": ["eng"],
            "skip_text_pages": False,
            "max_pixels": 1_000_000,
            "max_total_bytes": 1_000_000,
        },
    )


def _minimal_pdf(
    path: Path,
    *,
    user_unit: str = "1",
    crop_box: tuple[int, int, int, int] | None = None,
    rotation: int = 0,
    content: bytes = b"",
    resources: bytes = b"<< >>",
) -> Path:
    page_dictionary = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
        + f"/UserUnit {user_unit} ".encode("ascii")
    )
    if crop_box is not None:
        page_dictionary += (
            "/CropBox [" + " ".join(str(value) for value in crop_box) + "] "
        ).encode("ascii")
    if rotation:
        page_dictionary += f"/Rotate {rotation} ".encode("ascii")
    page_dictionary += b"/Resources " + resources + b" /Contents 4 0 R >>"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        page_dictionary,
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
        + content
        + b"\nendstream",
    ]
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for object_number, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{object_number} 0 obj\n".encode("ascii"))
        body.extend(payload)
        body.extend(b"\nendobj\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for offset in offsets:
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


def _mixed_image_text_pdf(path: Path) -> Path:
    content = (
        b"q 100 0 0 100 0 0 cm /Scan Do Q\n"
        b"BT /F1 10 Tf 2 2 Td (1) Tj ET"
    )
    image = b"\xff\xff\xff"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
        b"/Resources << /Font << /F1 5 0 R >> /XObject << /Scan 6 0 R >> >> "
        b"/Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
        + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length {len(image)} >>\n"
        f"stream\n".encode("ascii")
        + image
        + b"\nendstream",
    ]
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for object_number, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{object_number} 0 obj\n".encode("ascii") + payload + b"\nendobj\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f\r\n".encode("ascii"))
    for offset in offsets:
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


def _sufficient_text_pdf(path: Path) -> Path:
    content = (
        b"BT /F1 10 Tf 2 90 Td "
        b"(Embedded searchable text fills the first document region.) Tj "
        b"0 -40 Td (Another complete searchable paragraph fills the middle.) Tj "
        b"0 -40 Td (The final searchable paragraph covers the page bottom.) Tj ET"
    )
    resources = (
        b"<< /Font << /F1 << /Type /Font /Subtype /Type1 "
        b"/BaseFont /Helvetica >> >> >>"
    )
    return _minimal_pdf(path, content=content, resources=resources)
