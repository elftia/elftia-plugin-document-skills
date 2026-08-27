"""XLSX formula recalculation via a headless private ODS round trip (no macro).

LibreOffice preserves stale cached values during XLSX-to-XLSX conversion.
This module therefore stages the input XLSX, converts it through a bounded
private ODS artifact, and reads the recomputed cached values from the final
XLSX via the existing reader. The ODS artifact is never published.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core.io.temp_roots import OperationTempRoot
from ...formats.xlsx.mapping import map_workbook
from ...formats.xlsx.package import OpcPackage
from .input_snapshot import private_libreoffice_input
from .output import read_provider_output
from .runner import LibreOfficeRunner


@dataclass(frozen=True)
class RecalculatedXlsx:
    """Contained provider output and the formula records it actually produced."""

    payload: bytes
    formulas: dict[str, dict[str, Any]]

    @property
    def cached_values(self) -> dict[str, Any]:
        return {
            ref: record.get("cached_value")
            for ref, record in self.formulas.items()
        }


def recalculate_xlsx(
    input_xlsx: Path,
    runner: LibreOfficeRunner,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Recalculate XLSX formulas via a private XLSX-to-ODS-to-XLSX round trip.

    Returns a dict mapping ``sheet!cell`` references to their recalculated
    cached value strings. NO macro is executed.
    """
    return recalculate_xlsx_artifact(
        input_xlsx,
        runner,
        timeout_seconds=timeout_seconds,
    ).cached_values


def recalculate_xlsx_artifact(
    input_xlsx: Path,
    runner: LibreOfficeRunner,
    *,
    timeout_seconds: float,
) -> RecalculatedXlsx:
    """Return the isolated recalculated artifact plus its formula/value projection."""

    with private_libreoffice_input(
        input_xlsx,
        operation="libreoffice.recalc-xlsx",
    ) as snapshot:
        return recalculate_xlsx_snapshot_artifact(
            snapshot.path,
            runner,
            timeout_seconds=timeout_seconds,
        )


def recalculate_xlsx_snapshot_artifact(
    input_snapshot: Path,
    runner: LibreOfficeRunner,
    *,
    timeout_seconds: float,
) -> RecalculatedXlsx:
    """Recalculate an already screened private XLSX snapshot without restaging."""

    with OperationTempRoot() as private_root:
        intermediate_dir = private_root / "intermediate"
        intermediate_dir.mkdir()
        intermediate = runner.convert(
            input_snapshot,
            "ods",
            intermediate_dir,
            timeout_seconds=timeout_seconds,
        )
        output_dir = private_root / "output"
        output_dir.mkdir()
        converted = runner.convert(
            intermediate,
            "xlsx",
            output_dir,
            timeout_seconds=timeout_seconds,
        )
        formulas = _extract_formula_records(converted)
        return RecalculatedXlsx(
            payload=read_provider_output(converted, "xlsx"),
            formulas=formulas,
        )


def _extract_formula_records(converted_xlsx: Path) -> dict[str, dict[str, Any]]:
    """Read the converted XLSX and extract formula text, cached value, and type."""
    package = OpcPackage.open(converted_xlsx)
    workbook = map_workbook(package)
    result: dict[str, Any] = {}
    for sheet in workbook["sheets"]:
        sheet_name = sheet["name"]
        for row in sheet.get("rows", []):
            for cell in row.get("cells", []):
                formula = cell.get("formula")
                if formula:
                    ref = f"{sheet_name}!{cell['ref']}"
                    result[ref] = {
                        "formula": formula,
                        "cached_value": cell.get("cached_value"),
                        "type": cell.get("type", "n"),
                    }
    return result
