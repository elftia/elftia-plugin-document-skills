"""Validate the pinned presentation-contract package without copying schemas."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_PLUGIN_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_PLUGIN_SRC) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_SRC))

from document_skills_core.formats.pptx.presentation_contracts import (  # noqa: E402
    PresentationContractConsumer,
)


def check_contracts(contract_root: Path) -> dict[str, Any]:
    return PresentationContractConsumer.open(contract_root).summary()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: presentation_contract_conformance.py <package-root>", file=sys.stderr)
        return 2
    print(json.dumps(check_contracts(Path(sys.argv[1])), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
