"""Shell-free bounded runner for Poppler and Tesseract PDF tools."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.process import ProcessPolicy, ProcessRunner


class PdfToolRunner:
    def __init__(self, project_root: Path, *, process_runner: Any | None = None) -> None:
        self.project_root = project_root.resolve()
        self.policy = ProcessPolicy(self.project_root)
        self.runner = process_runner or ProcessRunner(self.policy)
        self._poppler: Path | None = None
        self._tesseract: Path | None = None
        self._languages: frozenset[str] = frozenset()

    def configure(
        self,
        paths: dict[str, Path],
        *,
        languages: frozenset[str] = frozenset(),
    ) -> None:
        self._poppler = None
        self._tesseract = None
        self._languages = languages
        if "pdftoppm" in paths:
            self._poppler = self.policy.allow_executable("poppler", paths["pdftoppm"])
        if "tesseract" in paths:
            self._tesseract = self.policy.allow_executable(
                "tesseract-ocr",
                paths["tesseract"],
            )

    def require_languages(self, languages: list[str]) -> None:
        missing = sorted(set(languages) - self._languages)
        if missing:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Tesseract does not provide every requested OCR language.",
                status="unavailable",
                details={"missing_languages": missing},
            )

    def render_page(
        self,
        source: Path,
        output_prefix: Path,
        *,
        page: int,
        dpi: int,
        output_format: str,
        max_output_bytes: int,
        timeout_seconds: float = 30.0,
    ) -> Path:
        if self._poppler is None:
            _unavailable("Poppler is not configured for rendering.")
        format_flag = "-png" if output_format == "png" else "-jpeg"
        result = self.runner.run(
            "poppler",
            self._poppler,
            [
                "-f",
                str(page),
                "-l",
                str(page),
                "-r",
                str(dpi),
                "-singlefile",
                format_flag,
                "-cropbox",
                str(source.resolve()),
                str(output_prefix.resolve()),
            ],
            cwd=self.project_root,
            timeout_seconds=timeout_seconds,
            output_limit=65_536,
        )
        if result.returncode != 0:
            _failed("Poppler rendering exited unsuccessfully.", result.returncode)
        suffix = ".png" if output_format == "png" else ".jpg"
        rendered = output_prefix.with_suffix(suffix)
        if not rendered.is_file() or rendered.stat().st_size <= 0:
            _failed("Poppler rendering produced no image artifact.")
        if rendered.stat().st_size > max_output_bytes:
            _unsafe("Poppler image output exceeds the remaining byte budget.")
        return rendered

    def ocr_tsv(
        self,
        image: Path,
        *,
        languages: list[str],
        max_output_bytes: int,
        timeout_seconds: float = 45.0,
    ) -> str:
        if self._tesseract is None:
            _unavailable("Tesseract is not configured for OCR.")
        self.require_languages(languages)
        result = self.runner.run(
            "tesseract-ocr",
            self._tesseract,
            [
                str(image.resolve()),
                "stdout",
                "-l",
                "+".join(languages),
                "tsv",
            ],
            cwd=self.project_root,
            timeout_seconds=timeout_seconds,
            output_limit=min(max_output_bytes, 8 * 1024 * 1024),
        )
        if result.returncode != 0:
            _failed("Tesseract OCR exited unsuccessfully.", result.returncode)
        return result.stdout


def _unavailable(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.PROVIDER_UNAVAILABLE,
        message,
        status="unavailable",
    )


def _failed(message: str, returncode: int | None = None) -> None:
    details = {} if returncode is None else {"returncode": returncode}
    raise DocumentSkillsError(ErrorCode.PROVIDER_FAILED, message, details=details)


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)
