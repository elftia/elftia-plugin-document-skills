"""Release-facing DOCX capability status must match the shipped public surface."""

from pathlib import Path


def test_docx_parity_matrix_distinguishes_shipped_and_deferred_capabilities(
    project_root: Path,
) -> None:
    report = (
        project_root / "provenance/parity/anthropic-capability-parity.md"
    ).read_text(encoding="utf-8")

    expected = {
        "Typed structural and formatting edit": "`PRESENT`",
        "Accessibility inspection": "`PRESENT`",
        "Image insertion/replacement in edit": "`PRESENT`",
        "Section and header/footer story edit": "`PRESENT`",
        "Bookmarks and internal hyperlinks": "`PRESENT`",
        "Safe fields and TOC dirty markers": "`PRESENT`",
        "Footnotes/endnotes edit": "`PRESENT`",
        "Simple content-control edit": "`PRESENT`",
        "Styles/numbering/theme inspection": "`PRESENT`",
        "Direct-formatting normalization report": "`PRESENT`",
        "Declarative template regions/style overlay": "`PRESENT`",
        "Template pack catalog/import/instantiate": "`PRESENT`",
        "Bounded high-fidelity graph merge": "`PRESENT`",
        ".dotx/.docm/legacy .doc handling": "`PRESENT`",
        "Comments threads/replies/resolution": "`PRESENT`",
        "LibreOffice render/page generation": "`PRESENT`",
        "Reference visual comparison QA": "`PRESENT`",
        "Full redline integrity scorecard": "`GAP`",
        "Threaded-comment extension merge": "`GAP`",
        "Complex revision graph merge": "`GAP`",
        "RTF/ODT public contracts": "`GAP`",
    }

    observed = _docx_statuses(report)
    for capability, status in expected.items():
        assert observed.get(capability) == status


def _docx_statuses(report: str) -> dict[str, str]:
    section = report.split("## DOCX capability matrix", 1)[1].split("## XLSX", 1)[0]
    statuses: dict[str, str] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().split("|")[1:-1]]
        if len(cells) >= 2 and cells[1] in {"`PRESENT`", "`GAP`", "`OUT-OF-SCOPE`"}:
            statuses[cells[0]] = cells[1]
    return statuses
