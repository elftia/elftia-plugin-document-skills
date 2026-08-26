from datetime import timedelta
import os
from pathlib import Path
import time
import zipfile

import pytest

from document_skills_core.core.contracts import DocumentSkillsError, ErrorCode
from document_skills_core.core.io import (
    ArchiveLimits,
    DangerousContentPolicy,
    OperationTempRoot,
    assert_distinct_paths,
    atomic_promote,
    cleanup_stale_roots,
    file_record,
    inspect_ooxml,
)
from document_skills_core.core.validation import validate_artifact


def _minimal_docx(path: Path, extra: dict[str, bytes] | None = None) -> None:
    parts = {
        "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "_rels/.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        "word/document.xml": b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
    }
    parts.update(extra or {})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)


def test_path_identity_staging_promotion_and_source_preservation(tmp_path):
    source = tmp_path / "source.docx"
    source.write_bytes(b"source")
    staged = tmp_path / "staged.docx"
    staged.write_bytes(b"output")
    original = file_record(source, "input")
    with pytest.raises(DocumentSkillsError) as same:
        assert_distinct_paths(source, source)
    assert same.value.code == ErrorCode.OUTPUT_EQUALS_INPUT
    output = atomic_promote(staged, tmp_path / "output.docx")
    assert output.sha256 != original.sha256
    assert file_record(source, "input").sha256 == original.sha256


def test_private_temp_cleanup_and_conservative_stale_cleanup(tmp_path):
    managed = tmp_path / "document-skills-operations"
    with OperationTempRoot(managed) as operation:
        (operation / "artifact.bin").write_bytes(b"x")
        operation_name = operation.name
    assert not (managed / operation_name).exists()
    stale = managed / "operation-stale"
    stale.mkdir()
    old = time.time() - 3600
    os.utime(stale, (old, old))
    unrelated = managed / "unrelated"
    unrelated.mkdir()
    removed = cleanup_stale_roots(
        base=managed, older_than=timedelta(seconds=1), limit=1
    )
    assert removed == ["operation-stale"]
    assert unrelated.exists()


def test_ooxml_preflight_rejects_traversal_and_budgets(tmp_path):
    unsafe = tmp_path / "unsafe.docx"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../escape.xml", "<x/>")
    with pytest.raises(DocumentSkillsError) as traversal:
        inspect_ooxml(unsafe)
    assert traversal.value.code == ErrorCode.ARCHIVE_UNSAFE
    large = tmp_path / "large.docx"
    _minimal_docx(large)
    with pytest.raises(DocumentSkillsError) as budget:
        inspect_ooxml(large, ArchiveLimits(max_entries=1))
    assert budget.value.details["budget"] == "entry_count"


def test_ooxml_preflight_normalizes_malformed_xml(tmp_path):
    malformed = tmp_path / "malformed.docx"
    _minimal_docx(
        malformed,
        {"word/document.xml": b"<w:document"},
    )
    with pytest.raises(DocumentSkillsError) as captured:
        inspect_ooxml(malformed)
    assert captured.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert captured.value.details["reason"] == "ParseError"


def test_ooxml_preflight_rejects_nested_content_type_declaration(tmp_path):
    document = tmp_path / "nested-content-type.docx"
    _minimal_docx(
        document,
        {
            "[Content_Types].xml": b"""\
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml">
    <Override PartName="/word/document.xml" ContentType="application/xml"/>
  </Default>
</Types>"""
        },
    )

    with pytest.raises(DocumentSkillsError) as captured:
        inspect_ooxml(document)
    assert captured.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert captured.value.details == {}


@pytest.mark.parametrize(
    "content_types",
    [
        pytest.param(
            b"""\
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Unexpected/>
</Types>""",
            id="unknown-child",
        ),
        pytest.param(
            b"""\
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml">payload</Default>
</Types>""",
            id="nonempty-declaration",
        ),
    ],
)
def test_ooxml_preflight_rejects_invalid_content_type_children(
    tmp_path,
    content_types,
):
    document = tmp_path / "invalid-content-types.docx"
    _minimal_docx(document, {"[Content_Types].xml": content_types})

    with pytest.raises(DocumentSkillsError) as captured:
        inspect_ooxml(document)
    assert captured.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert captured.value.details == {}


def test_visible_dde_prose_is_not_treated_as_a_field_instruction(tmp_path):
    document = tmp_path / "dde-prose.docx"
    _minimal_docx(
        document,
        {
            "word/document.xml": b"""\
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>DDE protocol overview</w:t></w:r></w:p></w:body>
</w:document>"""
        },
    )
    inspected = inspect_ooxml(document)
    assert inspected["security"]["counts"]["dde"] == 0
    assert inspected["security"]["dangerous"] is False


@pytest.mark.parametrize(
    "field_markup",
    [
        "<w:r><w:instrText>DDE cmd /c calc</w:instrText></w:r>",
        '<w:fldSimple w:instr="DDEAUTO cmd /c calc"/>',
    ],
)
def test_word_field_instructions_are_inventoried_as_dde(tmp_path, field_markup):
    document = tmp_path / "dde-field.docx"
    _minimal_docx(
        document,
        {
            "word/document.xml": f"""\
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p>{field_markup}</w:p></w:body>
</w:document>""".encode()
        },
    )
    with pytest.raises(DocumentSkillsError) as captured:
        inspect_ooxml(document)
    assert captured.value.code == ErrorCode.ARCHIVE_UNSAFE
    inventory = captured.value.details["security_inventory"]
    assert inventory["counts"]["dde"] == 1


def test_split_complex_word_field_instruction_is_inventoried_as_dde(tmp_path):
    document = tmp_path / "split-dde-field.docx"
    _minimal_docx(
        document,
        {
            "word/document.xml": b"""\
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p>
    <w:r><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:instrText>DD</w:instrText></w:r>
    <w:r><w:instrText>EAUTO cmd /c calc</w:instrText></w:r>
    <w:r><w:fldChar w:fldCharType="separate"/></w:r>
    <w:r><w:t>field result</w:t></w:r>
    <w:r><w:fldChar w:fldCharType="end"/></w:r>
  </w:p></w:body>
</w:document>"""
        },
    )
    with pytest.raises(DocumentSkillsError) as captured:
        inspect_ooxml(document)
    assert captured.value.code == ErrorCode.ARCHIVE_UNSAFE
    inventory = captured.value.details["security_inventory"]
    assert inventory["counts"]["dde"] == 1


def test_validation_gates_fail_closed_and_report_unavailable_enhancements(tmp_path):
    document = tmp_path / "sample.docx"
    _minimal_docx(document)
    report = validate_artifact(document, expected_format="docx")
    assert report["status"] == "fail"
    outcomes = {gate["id"]: gate["outcome"] for gate in report["gates"]}
    assert outcomes["ooxml.archive-xml"] == "pass"
    assert outcomes["provider.reopen"] == "unavailable"
    assert outcomes["visual.render"] == "unavailable"
    assert outcomes["schema.full"] == "unavailable"
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not-a-zip")
    failed = validate_artifact(broken, expected_format="docx")
    assert failed["status"] == "fail"


def test_source_preservation_failure_is_a_required_gate(tmp_path):
    document = tmp_path / "sample.docx"
    _minimal_docx(document)
    source = tmp_path / "source.docx"
    _minimal_docx(source)
    wrong_hash = "0" * 64
    report = validate_artifact(
        document,
        expected_format="docx",
        source_path=source,
        source_sha256=wrong_hash,
        reopen=lambda _path: "ok",
    )
    gate = next(item for item in report["gates"] if item["id"] == "source.preservation")
    assert report["status"] == "fail"
    assert gate["outcome"] == "fail"


def test_active_ooxml_content_is_inventoried_and_rejected_by_default(tmp_path):
    document = tmp_path / "active.docx"
    relationships = b"""\
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rVba" Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" Target="vbaProject.bin"/>
  <Relationship Id="rActiveX" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/control" Target="activeX/activeX1.xml"/>
  <Relationship Id="rOle" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" Target="embeddings/oleObject1.bin"/>
  <Relationship Id="rTemplate" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" Target="https://example.invalid/template.dotm" TargetMode="External"/>
  <Relationship Id="rExternal" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.invalid/" TargetMode="External"/>
</Relationships>"""
    content_types = b"""\
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/vbaProject.bin" ContentType="application/vnd.ms-office.vbaProject"/>
  <Override PartName="/word/activeX/activeX1.xml" ContentType="application/vnd.ms-office.activeX+xml"/>
  <Override PartName="/word/embeddings/oleObject1.bin" ContentType="application/vnd.openxmlformats-officedocument.oleObject"/>
</Types>"""
    document_xml = b"""\
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:instrText>DDEAUTO cmd /c calc</w:instrText></w:r></w:p></w:body>
</w:document>"""
    _minimal_docx(
        document,
        {
            "[Content_Types].xml": content_types,
            "word/document.xml": document_xml,
            "word/_rels/document.xml.rels": relationships,
            "word/vbaProject.bin": b"vba",
            "word/activeX/activeX1.xml": b"<activeX/>",
            "word/embeddings/oleObject1.bin": b"ole",
            "word/payload.exe": b"MZ",
        },
    )
    with pytest.raises(DocumentSkillsError) as rejected:
        inspect_ooxml(document)
    assert rejected.value.code == ErrorCode.ARCHIVE_UNSAFE
    inventory = rejected.value.details["security_inventory"]
    for category in (
        "vba",
        "activex",
        "ole",
        "templates",
        "dde",
        "external_targets",
        "executable_parts",
    ):
        assert inventory["counts"][category] > 0

    inspected = inspect_ooxml(
        document,
        dangerous_policy=DangerousContentPolicy.PRESERVE_DISABLED,
    )
    assert inspected["security"]["dangerous"] is True
    assert inspected["security"]["requires_disabled_preservation"] is True
    assert inspected["security"]["mutation_authorized"] is False

    validation = validate_artifact(document, expected_format="docx")
    archive_gate = next(
        gate for gate in validation["gates"] if gate["id"] == "ooxml.archive-xml"
    )
    assert archive_gate["outcome"] == "fail"
    assert archive_gate["evidence"]["security_inventory"]["counts"]["vba"] > 0


@pytest.mark.parametrize(
    ("part", "content_type", "relationship_type"),
    [
        (
            "xl/macrosheets/sheet1.xml",
            "application/vnd.ms-excel.macrosheet+xml",
            "http://schemas.microsoft.com/office/2006/relationships/xlMacrosheet",
        ),
        (
            "xl/intlMacrosheets/sheet1.xml",
            "application/vnd.ms-excel.intlmacrosheet+xml",
            "http://schemas.microsoft.com/office/2006/relationships/xlIntlMacrosheet",
        ),
        (
            "xl/macrosheets/sheet1.bin",
            "application/vnd.ms-excel.macrosheet",
            "http://schemas.microsoft.com/office/2006/relationships/xlMacrosheet",
        ),
        (
            "xl/externalLinks/addins/provider.xll",
            "application/vnd.ms-excel.addin.macroEnabled.main+xml",
            "http://schemas.microsoft.com/office/2006/relationships/xlAddIn",
        ),
    ],
)
def test_xlm_macro_and_addin_variants_are_inventoried_and_rejected(
    tmp_path, part, content_type, relationship_type
):
    document = tmp_path / "active-xlm.xlsx"
    content_types = f"""\
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/{part}" ContentType="{content_type}"/>
</Types>""".encode()
    relationships = f"""\
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rXlm" Type="{relationship_type}" Target="/{part}"/>
</Relationships>""".encode()
    payload = (
        b'<xm:macrosheet xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"/>'
        if part.endswith(".xml")
        else b"binary-xlm"
    )
    _minimal_docx(
        document,
        {
            "[Content_Types].xml": content_types,
            "xl/_rels/workbook.xml.rels": relationships,
            part: payload,
        },
    )
    with pytest.raises(DocumentSkillsError) as rejected:
        inspect_ooxml(document)
    inventory = rejected.value.details["security_inventory"]
    assert rejected.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert inventory["dangerous"] is True
    assert inventory["counts"]["xlm"] >= 2

    inspected = inspect_ooxml(
        document,
        dangerous_policy=DangerousContentPolicy.PRESERVE_DISABLED,
    )
    assert inspected["security"]["dangerous"] is True
    assert inspected["security"]["requires_disabled_preservation"] is True
    assert inspected["security"]["mutation_authorized"] is False


@pytest.mark.parametrize(
    "relationship_type",
    [
        "http://schemas.microsoft.com/office/2006/relationships/xlAddIn",
        "http://schemas.microsoft.com/office/2006/relationships/xlIntlAddIn",
        "http://schemas.microsoft.com/office/2006/relationships/xlMacrosheet",
        "http://schemas.microsoft.com/office/2006/relationships/xlIntlMacrosheet",
        "http://schemas.microsoft.com/office/2006/relationships/xlBinaryIndex",
    ],
)
def test_xlm_relationship_type_is_dangerous_with_neutral_target(
    tmp_path, relationship_type
):
    document = tmp_path / "relationship-only.xlsx"
    relationships = f"""\
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rActive" Type="{relationship_type}" Target="provider.dat"/>
</Relationships>""".encode()
    _minimal_docx(
        document,
        {"xl/_rels/workbook.xml.rels": relationships, "xl/provider.dat": b"data"},
    )
    with pytest.raises(DocumentSkillsError) as rejected:
        inspect_ooxml(document)
    assert rejected.value.details["security_inventory"]["counts"]["xlm"] == 1
    preserved = inspect_ooxml(
        document,
        dangerous_policy=DangerousContentPolicy.PRESERVE_DISABLED,
    )
    assert preserved["security"]["mutation_authorized"] is False


@pytest.mark.parametrize(
    ("part", "content_type", "payload"),
    [
        (
            "xl/custom/provider.dat",
            "application/vnd.ms-excel.addin.macroEnabled.main+xml",
            b"neutral",
        ),
        (
            "xl/custom/provider.dat",
            "application/vnd.ms-excel.sheet.binary.macroEnabled.main",
            b"neutral",
        ),
        (
            "xl/macrosheets/provider.dat",
            "application/octet-stream",
            b"neutral",
        ),
        (
            "xl/custom/provider.xml",
            "application/xml",
            b'<macroSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>',
        ),
        (
            "xl/custom/provider.xml",
            "application/xml",
            b'<xlIntlAddIn xmlns="urn:neutral"/>',
        ),
    ],
)
def test_each_xlm_part_content_type_and_root_signal_fails_closed(
    tmp_path, part, content_type, payload
):
    document = tmp_path / "signal-only.xlsx"
    content_types = f"""\
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/{part}" ContentType="{content_type}"/>
</Types>""".encode()
    _minimal_docx(
        document,
        {"[Content_Types].xml": content_types, part: payload},
    )
    with pytest.raises(DocumentSkillsError) as rejected:
        inspect_ooxml(document)
    inventory = rejected.value.details["security_inventory"]
    assert inventory["dangerous"] is True
    assert inventory["counts"]["xlm"] >= 1
    preserved = inspect_ooxml(
        document,
        dangerous_policy=DangerousContentPolicy.PRESERVE_DISABLED,
    )
    assert preserved["security"]["mutation_authorized"] is False
