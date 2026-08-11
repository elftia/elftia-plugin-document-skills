"""Command-line entry point for independent consumer qualification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .harness import qualify_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="document-skills-consumer")
    parser.add_argument("--format", dest="format_id", choices=("docx", "xlsx", "pptx", "pdf"), required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--expectations", type=Path)
    parser.add_argument("--office-policy", choices=("auto", "off"), default="auto")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    expectations = _load_expectations(args.expectations)
    report = qualify_artifact(
        format_id=args.format_id,
        operation=args.operation,
        artifact=args.artifact,
        expectations=expectations,
        office_policy=args.office_policy,
        timeout_seconds=args.timeout_seconds,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0 if report["status"] == "pass" else 1


def _load_expectations(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if type(payload) is not dict:
        raise ValueError("Consumer expectations must be a JSON object.")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
