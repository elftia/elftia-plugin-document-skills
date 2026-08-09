"""Cross-format malicious-fixture registry for the consolidated security gate.

This module is the single discovery point for every registered malicious fixture
across DOCX/XLSX/PPTX/PDF.  It enumerates the same malicious patterns exercised
by ``tests/test_safety.py`` and the per-format ``tests/test_{docx,xlsx,pptx,
pdf}_*.py`` suites and exposes them through one parametrized list so the
consolidated security gate can run each fixture against its format's mutation
and inspection paths uniformly.

Consolidation discipline (per Slice spec):

* On-disk DOCX fixtures (``tests/fixtures/docx-malicious-*.docx``) are
  referenced by relative path; the registry DOES NOT copy or fork them.
* Inline fixture patterns that the per-format suites build inside test bodies
  (DDE field in DOCX, XLM macro variants in XLSX, JavaScript / Launch / URI /
  GoToR / embedded-executable actions in PDF, VBA in PPTX) are reproduced by
  small builder helpers in this module.  Each builder carries a ``source_ref``
  citing the per-format test function that defines the canonical pattern.
  Builders live in this shared support module so the consolidated suite and any
  future per-format work reference the same shape; the per-format suites
  remain the per-format SSOT for behavior.

Each inline builder produces a valid OPC package (proper ``[Content_Types].xml``
and ``_rels/.rels``) so that the format's full ``OpcPackage.open()`` path
exercises the security inventory rather than a generic "missing part" rejection.
This matches the shape of the on-disk DOCX fixtures.

The registry is build-time / review-time only; it is NEVER packaged as an
agent-visible Skill surface.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal
import zipfile

__all__ = [
    "ExpectedBehavior",
    "MaliciousFixture",
    "FixtureKind",
    "discover_malicious_fixtures",
]


ExpectedBehavior = Literal[
    "container_reject",
    "inert_inventory",
]
"""How a fixture should be handled by the format's security gate.

``container_reject``: the package cannot even be opened inertly; both the
mutation path AND the inspection path raise ``DocumentSkillsError(
ARCHIVE_UNSAFE)`` (e.g. zip-slip traversal, malformed XML, over-budget
expansion).

``inert_inventory``: the package CAN be opened with
``allow_dangerous_inventory=True``; mutation fails closed with
``ARCHIVE_UNSAFE`` while inspection inventories the dangerous content under
``mutation_authorized: false``.
"""


FixtureKind = Literal[
    "on-disk",
    "built",
]
"""Whether the fixture is a path to an existing file or a builder callable."""


@dataclass(frozen=True)
class MaliciousFixture:
    """A single registered malicious fixture discovered by the registry."""

    format: Literal["docx", "xlsx", "pptx", "pdf"]
    pattern_id: str
    """Stable identifier (e.g. ``docx:zip-slip``, ``pdf:javascript-action``)."""

    expected_behavior: ExpectedBehavior
    """How the security gate should handle this fixture."""

    source_ref: str
    """Citation of the per-format test function that defines the canonical pattern."""

    on_disk_path: str | None = None
    """Project-root-relative path for on-disk fixtures (``FixtureKind == on-disk``)."""

    builder: Callable[[Path], Path] | None = None
    """Builder that writes the fixture to ``tmp_path`` and returns its path."""

    @property
    def kind(self) -> FixtureKind:
        return "on-disk" if self.on_disk_path is not None else "built"

    def materialize(self, project_root: Path, tmp_path: Path) -> Path:
        """Return the on-disk path of the fixture, materializing it if needed."""
        if self.on_disk_path is not None:
            return project_root / self.on_disk_path
        assert self.builder is not None, f"fixture {self.pattern_id} has no builder"
        return self.builder(tmp_path)


# ---------------------------------------------------------------------------
# Minimal valid OPC package bases (one per OOXML format)
# ---------------------------------------------------------------------------
#
# Each base is a complete, valid OPC package that will pass the format's
# structural validation.  Builders start from a base and inject dangerous
# content so the security inventory is the layer that rejects the package
# (not a generic "missing part" check).

_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE_DOC_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)


def _wrap_types(overrides: list[tuple[str, str]]) -> bytes:
    body = [f'<Types xmlns="{_CT_NS}">']
    for part_name, content_type in overrides:
        body.append(
            f'<Override PartName="{part_name}" ContentType="{content_type}"/>'
        )
    body.append("</Types>")
    return "".join(body).encode("utf-8")


def _wrap_rels(relationships: list[tuple[str, str, str, str | None]]) -> bytes:
    """Each relationship: (Id, Type, Target, TargetMode-or-None)."""
    body = [f'<Relationships xmlns="{_RELS_NS}">']
    for rel_id, rel_type, target, target_mode in relationships:
        attrs = f'Id="{rel_id}" Type="{rel_type}" Target="{target}"'
        if target_mode is not None:
            attrs += f' TargetMode="{target_mode}"'
        body.append(f"<Relationship {attrs}/>")
    body.append("</Relationships>")
    return "".join(body).encode("utf-8")


def _docx_base_parts() -> dict[str, bytes]:
    main_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    )
    return {
        "[Content_Types].xml": _wrap_types([("/word/document.xml", main_type)]),
        "_rels/.rels": _wrap_rels([("rId1", _OFFICE_DOC_REL, "word/document.xml", None)]),
        "word/document.xml": (
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b"<w:body><w:p/></w:body>"
            b"</w:document>"
        ),
    }


def _xlsx_base_parts() -> dict[str, bytes]:
    main_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    )
    worksheet_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
    )
    return {
        "[Content_Types].xml": _wrap_types(
            [
                ("/xl/workbook.xml", main_type),
                ("/xl/worksheets/sheet1.xml", worksheet_type),
            ]
        ),
        "_rels/.rels": _wrap_rels([("rId1", _OFFICE_DOC_REL, "xl/workbook.xml", None)]),
        "xl/workbook.xml": (
            b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            b' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            b'<sheets><sheet name="Sheet1" sheetId="1" r:id="rIdWs1"/></sheets>'
            b"</workbook>"
        ),
        "xl/_rels/workbook.xml.rels": _wrap_rels(
            [
                (
                    "rIdWs1",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
                    "worksheets/sheet1.xml",
                    None,
                )
            ]
        ),
        "xl/worksheets/sheet1.xml": (
            b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            b"<sheetData/>"
            b"</worksheet>"
        ),
    }


def _pptx_base_parts() -> dict[str, bytes]:
    main_type = (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
    )
    slide_type = (
        "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
    )
    return {
        "[Content_Types].xml": _wrap_types(
            [
                ("/ppt/presentation.xml", main_type),
                ("/ppt/slides/slide1.xml", slide_type),
            ]
        ),
        "_rels/.rels": _wrap_rels(
            [("rId1", _OFFICE_DOC_REL, "ppt/presentation.xml", None)]
        ),
        "ppt/presentation.xml": (
            b'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
            b' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            b'<sldIdLst><sldId id="1" r:id="rIdSlide1"/></sldIdLst>'
            b"</p:presentation>"
        ),
        "ppt/_rels/presentation.xml.rels": _wrap_rels(
            [
                (
                    "rIdSlide1",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
                    "slides/slide1.xml",
                    None,
                )
            ]
        ),
        "ppt/slides/slide1.xml": (
            b'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            b"<p:cSld><p:spTree/></p:cSld>"
            b"</p:sld>"
        ),
    }


def _write_package(path: Path, parts: dict[str, bytes]) -> Path:
    """Write a deterministic OOXML zip."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(parts):
            archive.writestr(name, parts[name])
    return path


# ---------------------------------------------------------------------------
# Inline builder helpers (reproduce per-format patterns; per-format SSOT cited)
# ---------------------------------------------------------------------------

def _build_docx_dde_field(tmp_path: Path) -> Path:
    """A valid DOCX whose document.xml carries an inline DDE field instruction.

    Source: ``tests/test_safety.py::test_word_field_instructions_are_inventoried_as_dde``.
    """
    parts = _docx_base_parts()
    parts["word/document.xml"] = (
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body><w:p>"
        b"<w:r><w:instrText>DDEAUTO cmd /c calc</w:instrText></w:r>"
        b"</w:p></w:body></w:document>"
    )
    return _write_package(tmp_path / "docx-dde-field.docx", parts)


def _build_xlsx_xlm_macrosheet(tmp_path: Path) -> Path:
    """A valid XLSX carrying an XLM macro-sheet content-type override + relationship.

    Source: ``tests/test_safety.py::test_xlm_macro_and_addin_variants_are_inventoried_and_rejected``.
    """
    parts = _xlsx_base_parts()
    part = "/xl/macrosheets/sheet1.xml"
    content_type = "application/vnd.ms-excel.macrosheet+xml"
    relationship_type = "http://schemas.microsoft.com/office/2006/relationships/xlMacrosheet"

    # Extend content types
    ct_root = _wrap_types(
        [
            ("/xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
            ("/xl/worksheets/sheet1.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"),
            (part, content_type),
        ]
    )
    parts["[Content_Types].xml"] = ct_root
    # Extend workbook relationships
    parts["xl/_rels/workbook.xml.rels"] = _wrap_rels(
        [
            (
                "rIdWs1",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
                "worksheets/sheet1.xml",
                None,
            ),
            (
                "rIdXlm",
                relationship_type,
                "macrosheets/sheet1.xml",
                None,
            ),
        ]
    )
    parts["xl/macrosheets/sheet1.xml"] = (
        b'<xm:macrosheet xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"/>'
    )
    return _write_package(tmp_path / "xlsx-xlm-macrosheet.xlsx", parts)


def _build_pptx_vba_project(tmp_path: Path) -> Path:
    """A valid PPTX carrying a VBA project relationship + content-type override.

    PPTX inherits the OOXML security inventory; a VBA project part should fail
    closed at the package preflight layer just like DOCX/XLSX.  This pattern is
    not yet covered by a per-format PPTX test; the consolidated gate surfaces it
    as a cross-format gap and asserts the uniform invariant.
    """
    parts = _pptx_base_parts()
    # Extend content types with VBA project
    parts["[Content_Types].xml"] = _wrap_types(
        [
            ("/ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"),
            ("/ppt/slides/slide1.xml", "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"),
            ("/ppt/vbaProject.bin", "application/vnd.ms-office.vbaProject"),
        ]
    )
    # Extend presentation relationships with VBA project
    parts["ppt/_rels/presentation.xml.rels"] = _wrap_rels(
        [
            (
                "rIdSlide1",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
                "slides/slide1.xml",
                None,
            ),
            (
                "rIdVba",
                "http://schemas.microsoft.com/office/2006/relationships/vbaProject",
                "vbaProject.bin",
                None,
            ),
        ]
    )
    parts["ppt/vbaProject.bin"] = b"VBA"
    return _write_package(tmp_path / "pptx-vba-project.pptx", parts)


def _build_pdf_action(tmp_path: Path, action_dict: str, name: str) -> Path:
    """Build a PDF with a Catalog /OpenAction (JavaScript/Launch/URI/GoToR).

    Source: ``tests/test_pdf_operations.py::_build_action_pdf``.
    """
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []

    def emit(content: bytes) -> None:
        num = len(offsets) + 1
        offsets.append(len(header) + len(body))
        body.extend(f"{num} 0 obj\n".encode("ascii"))
        body.extend(content)
        body.extend(b"\nendobj\n")

    emit(f"<< /Type /Catalog /Pages 2 0 R /OpenAction {action_dict} >>".encode("ascii"))
    emit(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    emit(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>")

    xref_offset = len(header) + len(body)
    size = len(offsets) + 1
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {size}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for off in offsets:
        xref.extend(f"{off:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


def _build_pdf_javascript(tmp_path: Path) -> Path:
    return _build_pdf_action(
        tmp_path, "<< /S /JavaScript /JS (app.alert(1)) >>", "pdf-javascript-action.pdf"
    )


def _build_pdf_launch(tmp_path: Path) -> Path:
    return _build_pdf_action(
        tmp_path, "<< /S /Launch /F (calc.exe) >>", "pdf-launch-action.pdf"
    )


def _build_pdf_uri(tmp_path: Path) -> Path:
    return _build_pdf_action(
        tmp_path,
        "<< /S /URI /URI (http://evil.example.com) >>",
        "pdf-uri-action.pdf",
    )


def _build_pdf_gotor(tmp_path: Path) -> Path:
    return _build_pdf_action(
        tmp_path, "<< /S /GoToR /F (external.pdf) >>", "pdf-gotor-action.pdf"
    )


def _build_pdf_embedded_executable(tmp_path: Path) -> Path:
    """Build a PDF with an embedded executable file.

    Source: ``tests/test_pdf_operations.py::_build_embedded_executable_pdf``.
    """
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []

    def emit(content: bytes) -> None:
        num = len(offsets) + 1
        offsets.append(len(header) + len(body))
        body.extend(f"{num} 0 obj\n".encode("ascii"))
        body.extend(content)
        body.extend(b"\nendobj\n")

    emit(b"<< /Type /Catalog /Pages 2 0 R >>")
    emit(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    emit(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/EF << /F << /Type /EmbeddedFile /Subtype (application/x-dosexec) >> >> >>"
    )

    xref_offset = len(header) + len(body)
    size = len(offsets) + 1
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {size}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for off in offsets:
        xref.extend(f"{off:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path = tmp_path / "pdf-embedded-executable.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


# ---------------------------------------------------------------------------
# On-disk DOCX fixtures (referenced in place; never copied)
# ---------------------------------------------------------------------------

_ON_DISK_DOCX_FIXTURES: tuple[tuple[str, ExpectedBehavior], ...] = (
    ("docx-malicious-absolute.docx", "container_reject"),
    ("docx-malicious-alias.docx", "container_reject"),
    ("docx-malicious-crc.docx", "container_reject"),
    ("docx-malicious-duplicate.docx", "container_reject"),
    ("docx-malicious-entity.docx", "container_reject"),
    ("docx-malicious-expansion.docx", "container_reject"),
    ("docx-malicious-path.docx", "container_reject"),
    ("docx-malicious-symlink.docx", "container_reject"),
    ("docx-malicious-xml-limit.docx", "container_reject"),
    ("docx-malicious-active.docx", "inert_inventory"),
)


# ---------------------------------------------------------------------------
# Public registry API
# ---------------------------------------------------------------------------

def discover_malicious_fixtures(project_root: Path) -> list[MaliciousFixture]:
    """Return every registered malicious fixture across all four formats.

    Order is deterministic: DOCX on-disk, DOCX built, XLSX built, PPTX built,
    PDF built.  New fixtures appended here are automatically picked up by the
    consolidated security gate.
    """
    fixtures: list[MaliciousFixture] = []

    # DOCX on-disk fixtures (referenced in place)
    fixture_root = project_root / "tests" / "fixtures"
    for name, behavior in _ON_DISK_DOCX_FIXTURES:
        path = fixture_root / name
        if path.is_file():
            fixtures.append(
                MaliciousFixture(
                    format="docx",
                    pattern_id=f"docx:on-disk:{name}",
                    expected_behavior=behavior,
                    source_ref="tests/test_docx_fixtures.py::test_security_matrix_distinguishes_container_rejection_from_inert_inventory",
                    on_disk_path=f"tests/fixtures/{name}",
                )
            )

    # DOCX inline patterns
    fixtures.append(
        MaliciousFixture(
            format="docx",
            pattern_id="docx:built:dde-field",
            expected_behavior="inert_inventory",
            source_ref="tests/test_safety.py::test_word_field_instructions_are_inventoried_as_dde",
            builder=_build_docx_dde_field,
        )
    )

    # XLSX inline patterns
    fixtures.append(
        MaliciousFixture(
            format="xlsx",
            pattern_id="xlsx:built:xlm-macrosheet",
            expected_behavior="inert_inventory",
            source_ref="tests/test_safety.py::test_xlm_macro_and_addin_variants_are_inventoried_and_rejected",
            builder=_build_xlsx_xlm_macrosheet,
        )
    )

    # PPTX inline patterns (PPTX has no per-format malicious suite today; the
    # consolidated gate asserts the uniform OOXML invariant for PPTX too.)
    fixtures.append(
        MaliciousFixture(
            format="pptx",
            pattern_id="pptx:built:vba-project",
            expected_behavior="inert_inventory",
            source_ref="tests/test_safety.py::test_active_ooxml_content_is_inventoried_and_rejected_by_default (PPTX inherits OOXML inventory)",
            builder=_build_pptx_vba_project,
        )
    )

    # PDF inline patterns
    fixtures.extend(
        [
            MaliciousFixture(
                format="pdf",
                pattern_id="pdf:built:javascript-action",
                expected_behavior="inert_inventory",
                source_ref="tests/test_pdf_operations.py::TestSecurityFailClosed::test_javascript_action_rejected_by_read",
                builder=_build_pdf_javascript,
            ),
            MaliciousFixture(
                format="pdf",
                pattern_id="pdf:built:launch-action",
                expected_behavior="inert_inventory",
                source_ref="tests/test_pdf_operations.py::TestSecurityFailClosed::test_launch_action_rejected_by_read",
                builder=_build_pdf_launch,
            ),
            MaliciousFixture(
                format="pdf",
                pattern_id="pdf:built:uri-action",
                expected_behavior="inert_inventory",
                source_ref="tests/test_pdf_operations.py::TestSecurityFailClosed::test_uri_action_rejected_by_read",
                builder=_build_pdf_uri,
            ),
            MaliciousFixture(
                format="pdf",
                pattern_id="pdf:built:gotor-action",
                expected_behavior="inert_inventory",
                source_ref="tests/test_pdf_operations.py::TestSecurityFailClosed::test_gotor_action_rejected_by_read",
                builder=_build_pdf_gotor,
            ),
            MaliciousFixture(
                format="pdf",
                pattern_id="pdf:built:embedded-executable",
                expected_behavior="inert_inventory",
                source_ref="tests/test_pdf_operations.py::TestSecurityFailClosed::test_embedded_executable_rejected_by_read",
                builder=_build_pdf_embedded_executable,
            ),
        ]
    )

    return fixtures
