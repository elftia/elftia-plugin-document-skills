"""Tagged LibreOffice PDF render subsets retain visual content and fail closed."""

import hashlib

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.docx.render_pdf_projection import split_render_pages
from document_skills_core.formats.pdf.edit import edit_pdf
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from tests.test_pdf_page_tree_catalog_preservation import _write_pdf, _stream


def _tagged_pdf(path, *, action=b"[3 0 R /XYZ null null 0]", extra=b""):
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R /OpenAction " + action
        + b" /StructTreeRoot 7 0 R /MarkInfo << /Marked true >> /Lang (en-US) " + extra + b" >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] /Contents 5 0 R /StructParents 0 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] /Contents 6 0 R /StructParents 1 >>",
        _stream(b"q 1 0 0 rg 0 0 20 20 re f Q"),
        _stream(b"q 0 1 0 rg 0 0 30 30 re f Q"),
        b"<< /Type /StructTreeRoot /K [] >>",
    ])


@pytest.mark.parametrize("page", [1,2])
def test_tagged_render_projection_selects_pages_without_semantic_claims(tmp_path, page):
    source = _tagged_pdf(tmp_path / "source.pdf")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "render.pdf"
    split_render_pages(source, output, page, page)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    model = parse_pdf(output)
    pages = walk_pages(model)
    assert len(pages) == 1
    root = model.get_object(model.catalog_ref).value
    assert root.get("/Lang") == "en-US"
    assert not set(root.entries) & {"/StructTreeRoot", "/MarkInfo", "/OpenAction"}
    assert "/StructParents" not in model.objects[pages[0].obj_num].value.entries
    expected = b"1 0 0 rg" if page == 1 else b"0 1 0 rg"
    assert expected in output.read_bytes()
    with pytest.raises(DocumentSkillsError) as error:
        edit_pdf(source, tmp_path / "general-edit.pdf",
                 {"primitives": [{"type":"split", "page_ranges":[[page,page]]}]})
    assert error.value.code == ErrorCode.ENHANCEMENT_REQUIRED


@pytest.mark.parametrize("action", [
    b"<< /S /JavaScript /JS (alert) >>", b"<< /S /Launch /F (program) >>",
    b"<< /S /URI /URI (https://example.invalid) >>",
])
def test_render_projection_rejects_active_actions_before_removing_navigation(tmp_path, action):
    source = _tagged_pdf(tmp_path / "source.pdf", action=action)
    output = tmp_path / "rejected.pdf"
    with pytest.raises(DocumentSkillsError) as error:
        split_render_pages(source, output, 1, 1)
    assert error.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert not output.exists()


@pytest.mark.parametrize("action", [b"(named-destination)", b"<< /S /Unknown /D [3 0 R /Fit] >>"])
def test_render_projection_rejects_unreconciled_initial_action(tmp_path, action):
    source = _tagged_pdf(tmp_path / "source.pdf", action=action)
    with pytest.raises(DocumentSkillsError) as error:
        split_render_pages(source, tmp_path / "rejected.pdf", 1, 1)
    assert error.value.code == ErrorCode.ENHANCEMENT_REQUIRED


def test_render_projection_keeps_other_catalog_rejections(tmp_path):
    source = _tagged_pdf(tmp_path / "source.pdf", extra=b"/Names << >>")
    output = tmp_path / "rejected.pdf"
    with pytest.raises(DocumentSkillsError) as error:
        split_render_pages(source, output, 1, 1)
    assert error.value.code == ErrorCode.ENHANCEMENT_REQUIRED
    assert not output.exists()


def test_native_pdf_raster_input_is_byte_detected_and_operation_restricted(tmp_path):
    from document_skills_core.providers.libreoffice.input_snapshot import private_libreoffice_input

    source = _tagged_pdf(tmp_path / "original.pdf")
    page = tmp_path / "page.disguised"
    split_render_pages(source, page, 1, 1)
    digest = hashlib.sha256(page.read_bytes()).hexdigest()
    with private_libreoffice_input(page, operation="libreoffice.render-image") as snapshot:
        assert snapshot.actual_format == "pdf"
        assert snapshot.path.suffix == ".pdf"
        assert hashlib.sha256(snapshot.path.read_bytes()).hexdigest() == digest
    assert hashlib.sha256(page.read_bytes()).hexdigest() == digest
    with pytest.raises(DocumentSkillsError) as error:
        with private_libreoffice_input(page, operation="libreoffice.convert-pdf"):
            pytest.fail("PDF admitted to Office conversion")
    assert error.value.code == ErrorCode.REQUEST_INVALID


@pytest.mark.parametrize("active", [False,True])
def test_native_pdf_raster_rejects_multiple_pages_and_active_input(tmp_path, active):
    from document_skills_core.providers.libreoffice.input_snapshot import private_libreoffice_input

    action = b"<< /S /JavaScript /JS (alert) >>" if active else b"[3 0 R /XYZ null null 0]"
    source = _tagged_pdf(tmp_path / "source.pdf", action=action)
    with pytest.raises(DocumentSkillsError) as error:
        with private_libreoffice_input(source, operation="libreoffice.render-image"):
            pytest.fail("Unsafe or multipage raster input admitted")
    assert error.value.code == (ErrorCode.ARCHIVE_UNSAFE if active else ErrorCode.REQUEST_INVALID)
