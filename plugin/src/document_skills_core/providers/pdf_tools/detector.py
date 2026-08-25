"""Callable, version-bounded detection for Poppler and Tesseract."""

from collections.abc import Callable
from pathlib import Path
import re
import shutil
from typing import Any

from document_skills_core.core.capabilities import DetectionEvidence
from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.core.process import ProcessPolicy, ProcessRunner

_POPPLER_VERSION = re.compile(r"(?:pdftoppm version|version)\s+([0-9]+(?:\.[0-9]+){1,3})", re.I)
_TESSERACT_VERSION = re.compile(r"^tesseract\s+([0-9]+(?:\.[0-9]+){1,3})", re.I)
_LANGUAGE = re.compile(r"^[A-Za-z0-9_]{2,16}$")
_POPPLER_RANGE = ((23, 1, 0, 0), (27, 0, 0, 0))
_TESSERACT_RANGE = ((5, 3, 0, 0), (6, 0, 0, 0))


class PdfToolDetector:
    def __init__(
        self,
        project_root: Path,
        *,
        require_tesseract: bool,
        path_finder: Callable[[str], str | None] = shutil.which,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.require_tesseract = require_tesseract
        self._path_finder = path_finder
        self._policy = ProcessPolicy(self.project_root)
        self._runner = process_runner or ProcessRunner(self._policy)
        self._accepted: dict[str, Path] = {}
        self._versions: dict[str, str] = {}
        self._languages: frozenset[str] = frozenset()

    def detect(self) -> DetectionEvidence:
        self._accepted = {}
        self._versions = {}
        self._languages = frozenset()
        poppler = self._probe(
            "pdftoppm",
            ["-v"],
            _POPPLER_VERSION,
            _POPPLER_RANGE,
        )
        if isinstance(poppler, DetectionEvidence):
            return poppler
        poppler_path, poppler_version = poppler
        self._accepted["pdftoppm"] = poppler_path
        self._versions["pdftoppm"] = poppler_version
        if not self.require_tesseract:
            return DetectionEvidence(
                True,
                version=poppler_version,
                path=str(poppler_path),
            )
        tesseract = self._probe(
            "tesseract",
            ["--version"],
            _TESSERACT_VERSION,
            _TESSERACT_RANGE,
        )
        if isinstance(tesseract, DetectionEvidence):
            return tesseract
        tesseract_path, tesseract_version = tesseract
        self._accepted["tesseract"] = tesseract_path
        self._versions["tesseract"] = tesseract_version
        languages = self._probe_languages(tesseract_path)
        if isinstance(languages, DetectionEvidence):
            self._accepted = {}
            return languages
        if "eng" not in languages:
            self._accepted = {}
            return DetectionEvidence(
                False,
                reason="The detected Tesseract installation lacks the required eng language pack.",
                path=str(tesseract_path),
            )
        self._languages = frozenset(languages)
        return DetectionEvidence(
            True,
            version=f"poppler-{poppler_version}+tesseract-{tesseract_version}",
            path=str(tesseract_path),
        )

    def accepted_paths(self) -> dict[str, Path]:
        return dict(self._accepted)

    def accepted_languages(self) -> frozenset[str]:
        return self._languages

    def diagnostics(self) -> dict[str, Any]:
        evidence = self.detect()
        return {
            "available": evidence.available,
            "version": evidence.version,
            "executables": {
                name: str(path) for name, path in sorted(self._accepted.items())
            },
            "executable_versions": dict(sorted(self._versions.items())),
            "tesseract_languages": sorted(self._languages),
            "reason": evidence.reason,
        }

    def _probe(
        self,
        name: str,
        arguments: list[str],
        version_pattern: re.Pattern[str],
        supported_range: tuple[tuple[int, int, int, int], tuple[int, int, int, int]],
    ) -> tuple[Path, str] | DetectionEvidence:
        candidate = self._path_finder(name)
        if candidate is None:
            return DetectionEvidence(
                False,
                reason=f"The required {name} executable is unavailable.",
            )
        try:
            executable = self._policy.allow_executable("runtime-detection", candidate)
            result = self._runner.run(
                "runtime-detection",
                executable,
                arguments,
                cwd=self.project_root,
                timeout_seconds=3.0,
                output_limit=16_384,
            )
        except DocumentSkillsError:
            return DetectionEvidence(
                False,
                reason=f"The detected {name} executable failed its callability probe.",
                path=candidate,
            )
        if result.returncode != 0:
            return DetectionEvidence(
                False,
                reason=f"The detected {name} executable rejected its version probe.",
                path=candidate,
            )
        output = "\n".join((result.stdout, result.stderr)).strip()
        match = version_pattern.search(output)
        if match is None:
            return DetectionEvidence(
                False,
                reason=f"The detected {name} version evidence was unparseable.",
                path=candidate,
            )
        version = match.group(1)
        parsed_version = _version_tuple(version)
        minimum, maximum = supported_range
        if not minimum <= parsed_version < maximum:
            return DetectionEvidence(
                False,
                version=version,
                reason=(
                    f"The detected {name} version is outside the supported range "
                    f"{_display_version(minimum)}..<{_display_version(maximum)}."
                ),
                path=str(executable),
            )
        return executable, version

    def _probe_languages(
        self,
        executable: Path,
    ) -> set[str] | DetectionEvidence:
        try:
            result = self._runner.run(
                "runtime-detection",
                executable,
                ["--list-langs"],
                cwd=self.project_root,
                timeout_seconds=3.0,
                output_limit=65_536,
            )
        except DocumentSkillsError:
            return DetectionEvidence(
                False,
                reason="The detected Tesseract language-pack probe failed.",
                path=str(executable),
            )
        if result.returncode != 0:
            return DetectionEvidence(
                False,
                reason="The detected Tesseract installation rejected --list-langs.",
                path=str(executable),
            )
        output = "\n".join((result.stdout, result.stderr))
        languages = {
            line.strip()
            for line in output.splitlines()
            if _LANGUAGE.fullmatch(line.strip()) is not None
        }
        if not languages:
            return DetectionEvidence(
                False,
                reason="The detected Tesseract language evidence was unparseable.",
                path=str(executable),
            )
        return languages


def _version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in version.split(".")]
    return tuple((parts + [0, 0, 0, 0])[:4])  # type: ignore[return-value]


def _display_version(version: tuple[int, int, int, int]) -> str:
    return ".".join(str(part) for part in version[:3])
