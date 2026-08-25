"""Execute truthful PDF provider-profile smoke tests through the public CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import subprocess
import sys
import tempfile
from typing import Any


PROFILES = ("core-only", "render", "ocr", "full")
CORE_BINDINGS = {
    "pdf.create": "core-python",
    "pdf.edit": "core-python",
    "pdf.rewrite.apply": "core-python",
}
PROFILE_BINDINGS = {
    "render": {"pdf.render": "poppler"},
    "ocr": {"pdf.ocr": "tesseract-ocr"},
    "full": {
        "pdf.render": "poppler",
        "pdf.ocr": "tesseract-ocr",
        "pdf.encrypt": "pypdf",
        "pdf.decrypt": "pypdf",
        "pdf.compress": "pypdf",
    },
}
OPTIONAL_BINDINGS = {"pdf.render": "poppler", "pdf.ocr": "tesseract-ocr"}


class ProfileFailure(RuntimeError):
    """Stable harness failure suitable for a machine-readable receipt."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PublicPdfCli:
    """Invoke the real public PDF supervisor using the active frozen environment."""

    def __init__(self, project_root: Path, cwd: Path, env: dict[str, str]) -> None:
        self.project_root = project_root.resolve()
        self.cwd = cwd.resolve()
        self.env = env
        self.script = self.project_root / "skills/document-pdf/scripts/run.py"

    def invoke(
        self, *arguments: str, timeout: float = 360.0
    ) -> tuple[int, dict[str, Any]]:
        process = subprocess.run(
            [sys.executable, str(self.script), *arguments],
            cwd=self.cwd,
            env=self.env,
            check=False,
            capture_output=True,
            text=False,
            shell=False,
            timeout=timeout,
        )
        if process.stderr:
            raise ProfileFailure(
                "public_cli_stderr", "The public PDF command wrote to stderr."
            )
        try:
            text = process.stdout.decode("utf-8", errors="strict")
            payload, end = json.JSONDecoder().raw_decode(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProfileFailure(
                "public_cli_malformed",
                "The public PDF command returned malformed JSON.",
            ) from error
        if text[end:].strip() or type(payload) is not dict:
            raise ProfileFailure(
                "public_cli_malformed",
                "The public PDF command returned a non-canonical payload.",
            )
        return process.returncode, payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=PROFILES)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when an optional provider is unavailable.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def capability_indexes(
    payload: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if payload.get("schema_version") != "1.0":
        raise ProfileFailure(
            "capability_report_malformed", "Capability schema_version is invalid."
        )
    operations = _record_index(payload.get("operations"), "operation")
    providers = _record_index(payload.get("providers"), "id")
    for operation, record in operations.items():
        bound = record.get("providers")
        if type(record.get("available")) is not bool or type(bound) is not list:
            raise ProfileFailure(
                "capability_report_malformed",
                f"Capability {operation} has invalid fields.",
            )
        if any(type(provider) is not str or not provider for provider in bound):
            raise ProfileFailure(
                "capability_report_malformed",
                f"Capability {operation} has invalid providers.",
            )
        if record.get("reason") is not None and type(record.get("reason")) is not str:
            raise ProfileFailure(
                "capability_report_malformed",
                f"Capability {operation} has an invalid reason.",
            )
    for provider, record in providers.items():
        if type(record.get("available")) is not bool:
            raise ProfileFailure(
                "capability_report_malformed",
                f"Provider {provider} has invalid availability.",
            )
    return operations, providers


def assess_profile(
    profile: str, payload: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    operations, providers = capability_indexes(payload)
    bindings = CORE_BINDINGS if profile == "core-only" else PROFILE_BINDINGS[profile]
    requirements: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    for operation, provider in bindings.items():
        operation_record = operations.get(operation)
        provider_record = providers.get(provider)
        if operation_record is None or provider_record is None:
            raise ProfileFailure(
                "capability_report_malformed",
                f"Required binding is absent: {operation}.",
            )
        available = operation_record["available"]
        record = {
            "operation": operation,
            "provider": provider,
            "available": available,
            "version": provider_record.get("version"),
            "path": provider_record.get("path"),
            "reason": provider_record.get("reason") or operation_record.get("reason"),
        }
        requirements.append(record)
        if not available:
            unavailable.append(record)
            continue
        if (
            provider not in operation_record["providers"]
            or not provider_record["available"]
        ):
            raise ProfileFailure(
                "capability_binding_mismatch",
                f"Available capability {operation} lacks {provider}.",
            )
    if profile == "core-only":
        for operation, provider in OPTIONAL_BINDINGS.items():
            record = operations.get(operation)
            provider_record = providers.get(provider)
            if record is None or provider_record is None:
                raise ProfileFailure(
                    "capability_report_malformed",
                    f"Optional capability is absent: {operation}.",
                )
            requirements.append(
                {
                    "operation": operation,
                    "provider": provider,
                    "available": record["available"],
                    "version": provider_record.get("version"),
                    "path": provider_record.get("path"),
                    "reason": provider_record.get("reason") or record.get("reason"),
                }
            )
            if (
                record["available"]
                or record["providers"]
                or provider_record["available"]
            ):
                raise ProfileFailure(
                    "core_only_provider_visible",
                    f"Core-only isolation exposes {operation}.",
                )
        if unavailable:
            raise ProfileFailure(
                "core_capability_unavailable",
                "A required Core capability is unavailable.",
            )
    return requirements, unavailable


def _record_index(value: Any, key: str) -> dict[str, dict[str, Any]]:
    if type(value) is not list:
        raise ProfileFailure(
            "capability_report_malformed", f"Capability {key} records are invalid."
        )
    records: dict[str, dict[str, Any]] = {}
    for record in value:
        if (
            type(record) is not dict
            or type(record.get(key)) is not str
            or not record[key]
        ):
            raise ProfileFailure(
                "capability_report_malformed", f"Capability {key} record is invalid."
            )
        identity = record[key]
        if identity in records:
            raise ProfileFailure(
                "capability_report_malformed",
                f"Duplicate capability {key}: {identity}.",
            )
        records[identity] = record
    return records


def run_profile(profile: str, project_root: Path, *, strict: bool) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="elftia-pdf-profile-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        environment = dict(os.environ)
        if profile == "core-only":
            empty_path = root / "empty-path"
            empty_path.mkdir()
            for key in list(environment):
                if key.upper() == "PATH":
                    del environment[key]
            environment["PATH"] = str(empty_path)
        cli = PublicPdfCli(project_root, root, environment)
        return_code, capabilities = cli.invoke("capabilities", "--json", timeout=60.0)
        if return_code != 0:
            raise ProfileFailure(
                "capability_command_failed", "Public capability discovery failed."
            )
        requirements, unavailable = assess_profile(profile, capabilities)
        base = _receipt_base(profile, strict, requirements)
        if unavailable and profile != "full":
            return _unavailable_receipt(base, unavailable, [])
        available = {item["operation"] for item in requirements if item["available"]}
        smokes = _run_smokes(profile, cli, root, available)
        if unavailable:
            return _unavailable_receipt(base, unavailable, smokes)
        return {**base, "status": "pass", "reason": None, "smokes": smokes}


def _unavailable_receipt(
    base: dict[str, Any],
    unavailable: list[dict[str, Any]],
    smokes: list[dict[str, str]],
) -> dict[str, Any]:
    reason = {
        "code": "required_provider_unavailable",
        "bindings": unavailable,
        "operations": sorted(item["operation"] for item in unavailable),
    }
    return {**base, "status": "unavailable", "reason": reason, "smokes": smokes}


def _run_smokes(
    profile: str, cli: PublicPdfCli, root: Path, available: set[str]
) -> list[dict[str, str]]:
    source, create = _smoke_create(cli, root)
    smokes = [create]
    if profile in {"core-only", "full"}:
        smokes.extend(_smoke_core_mutations(cli, root, source, create["evidence"]))
    if profile in {"render", "full"} and "pdf.render" in available:
        smokes.append(_smoke_archive(cli, root, source, "pdf.render", "poppler"))
    if profile in {"ocr", "full"} and "pdf.ocr" in available:
        smokes.append(_smoke_archive(cli, root, source, "pdf.ocr", "tesseract-ocr"))
    if profile == "full" and {"pdf.encrypt", "pdf.decrypt", "pdf.compress"}.issubset(
        available
    ):
        smokes.extend(_smoke_pypdf(cli, root, source))
    for smoke in smokes:
        smoke.pop("evidence", None)
    return smokes


def _smoke_create(cli: PublicPdfCli, root: Path) -> tuple[Path, dict[str, Any]]:
    output = root / "created.pdf"
    payload = {
        "schema_version": "1.0",
        "operation": "pdf.create",
        "output": str(output),
        "arguments": {
            "document": {
                "metadata": {
                    "title": "Provider profile",
                    "author": "Elftia",
                    "subject": "",
                },
                "page_size": "A4",
                "pages": [
                    {
                        "blocks": [
                            {
                                "type": "heading",
                                "text": "Provider profile smoke",
                                "style": None,
                                "table": None,
                                "image": None,
                                "shape": None,
                            }
                        ],
                        "metadata": None,
                    }
                ],
            }
        },
    }
    result = _request(cli, root, "create", payload, "core-python", output)
    try:
        evidence = result["diagnostics"]["operation_result"]["creation"]["text_blocks"][
            0
        ]
    except (KeyError, IndexError, TypeError) as error:
        raise ProfileFailure(
            "smoke_evidence_missing", "Create smoke lacks text evidence."
        ) from error
    return output, {
        "id": "core-create",
        "operation": "pdf.create",
        "status": "pass",
        "provider": "core-python",
        "evidence": evidence,
    }


def _smoke_core_mutations(
    cli: PublicPdfCli, root: Path, source: Path, evidence: dict[str, Any]
) -> list[dict[str, str]]:
    edit_output = root / "edited.pdf"
    _request(
        cli,
        root,
        "edit",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(edit_output),
            "arguments": {
                "primitives": [{"type": "rotate", "pages": [1], "degrees": 90}]
            },
        },
        "core-python",
        edit_output,
    )
    rewrite_output = root / "rewritten.pdf"
    _request(
        cli,
        root,
        "rewrite",
        {
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": str(source),
            "output": str(rewrite_output),
            "arguments": {
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "blocks": [
                    {
                        "page": evidence["page"],
                        "bbox": evidence["bbox"],
                        "text": evidence["text"],
                        "font": str(evidence["font"]).removeprefix("/"),
                        "size": evidence["size"],
                        "color": evidence["color"],
                    }
                ],
                "rewrites": [{"block_index": 0, "text": "Provider verified"}],
            },
        },
        "core-python",
        rewrite_output,
    )
    form_source = _text_form_pdf(root / "form.pdf")
    form_output = root / "filled-form.pdf"
    _request(
        cli,
        root,
        "form",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(form_source),
            "output": str(form_output),
            "arguments": {
                "primitives": [
                    {
                        "type": "form_fill",
                        "fields": {"name": "Profile verified"},
                        "flatten": False,
                    }
                ]
            },
        },
        "core-python",
        form_output,
    )
    return [
        {
            "id": "core-edit",
            "operation": "pdf.edit",
            "status": "pass",
            "provider": "core-python",
        },
        {
            "id": "core-rewrite",
            "operation": "pdf.rewrite.apply",
            "status": "pass",
            "provider": "core-python",
        },
        {
            "id": "core-forms",
            "operation": "pdf.edit",
            "status": "pass",
            "provider": "core-python",
        },
    ]


def _smoke_archive(
    cli: PublicPdfCli, root: Path, source: Path, operation: str, provider: str
) -> dict[str, str]:
    stem = operation.removeprefix("pdf.")
    output = root / f"{stem}.zip"
    arguments: dict[str, Any] = {
        "pages": [1],
        "dpi": 144,
        "max_pixels": 20_000_000,
        "max_total_bytes": 32 * 1024 * 1024,
    }
    if operation == "pdf.render":
        arguments["format"] = "png"
    else:
        arguments.update({"languages": ["eng"], "skip_text_pages": False})
    _request(
        cli,
        root,
        stem,
        {
            "schema_version": "1.0",
            "operation": operation,
            "input": str(source),
            "output": str(output),
            "arguments": arguments,
        },
        provider,
        output,
        timeout=360.0,
    )
    return {"id": stem, "operation": operation, "status": "pass", "provider": provider}


def _smoke_pypdf(cli: PublicPdfCli, root: Path, source: Path) -> list[dict[str, str]]:
    encrypted = root / "encrypted.pdf"
    user_password = secrets.token_urlsafe(18)
    owner_password = secrets.token_urlsafe(18)
    _request(
        cli,
        root,
        "encrypt",
        {
            "schema_version": "1.0",
            "operation": "pdf.encrypt",
            "input": str(source),
            "output": str(encrypted),
            "secrets": {
                "user_password": user_password,
                "owner_password": owner_password,
            },
            "arguments": {
                "algorithm": "AES-256-R5",
                "permissions": ["print", "extract"],
                "encrypt_metadata": True,
            },
        },
        "pypdf",
        encrypted,
    )
    decrypted = root / "decrypted.pdf"
    _request(
        cli,
        root,
        "decrypt",
        {
            "schema_version": "1.0",
            "operation": "pdf.decrypt",
            "input": str(encrypted),
            "output": str(decrypted),
            "secrets": {"password": user_password},
            "arguments": {},
        },
        "pypdf",
        decrypted,
    )
    compress_source = _compressible_pdf(root / "compressible.pdf")
    compressed = root / "compressed.pdf"
    _request(
        cli,
        root,
        "compress",
        {
            "schema_version": "1.0",
            "operation": "pdf.compress",
            "input": str(compress_source),
            "output": str(compressed),
            "arguments": {"mode": "lossless"},
        },
        "pypdf",
        compressed,
    )
    return [
        {
            "id": "encrypt",
            "operation": "pdf.encrypt",
            "status": "pass",
            "provider": "pypdf",
        },
        {
            "id": "decrypt",
            "operation": "pdf.decrypt",
            "status": "pass",
            "provider": "pypdf",
        },
        {
            "id": "compress",
            "operation": "pdf.compress",
            "status": "pass",
            "provider": "pypdf",
        },
    ]


def _request(
    cli: PublicPdfCli,
    root: Path,
    name: str,
    payload: dict[str, Any],
    provider: str,
    output: Path,
    *,
    timeout: float = 90.0,
) -> dict[str, Any]:
    request_path = root / f"{name}.json"
    request_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    request_path.chmod(0o600)
    return_code, result = cli.invoke(
        "run", "--request", str(request_path), timeout=timeout
    )
    if return_code != 0 or result.get("status") != "success":
        raise ProfileFailure(
            "public_smoke_failed", f"Public smoke failed: {payload['operation']}."
        )
    chain = result.get("provider_chain")
    if type(chain) is not list or not chain or chain[0] != provider:
        raise ProfileFailure(
            "smoke_provider_mismatch", f"Wrong smoke provider: {payload['operation']}."
        )
    if not output.is_file() or output.stat().st_size == 0:
        raise ProfileFailure(
            "smoke_artifact_missing",
            f"Public smoke produced no artifact: {payload['operation']}.",
        )
    return result


def _text_form_pdf(path: Path) -> Path:
    return _write_pdf(
        path,
        [
            b"<< /Type /Catalog /Pages 2 0 R /AcroForm 7 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /Helv 5 0 R >> >> /Contents 4 0 R /Annots [6 0 R] >>",
            b"<< /Length 0 >>\nstream\n\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (name) /V () /Rect [72 700 300 730] /P 3 0 R /DA (/Helv 12 Tf 0 g) >>",
            b"<< /Fields [6 0 R] /DR << /Font << /Helv 5 0 R >> >> /DA (/Helv 12 Tf 0 g) >>",
        ],
    )


def _compressible_pdf(path: Path) -> Path:
    lines = [
        f"(Provider profile line {index % 10}) Tj 0 -14 Td".encode("ascii")
        for index in range(500)
    ]
    content = b"BT /F1 12 Tf 72 720 Td\n" + b"\n".join(lines) + b"\nET"
    return _write_pdf(
        path,
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ],
    )


def _write_pdf(path: Path, objects: list[bytes]) -> Path:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{number} 0 obj\n".encode("ascii") + payload + b"\nendobj\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(
        f"xref\n0 {len(objects) + 1}\n0000000000 65535 f\r\n".encode("ascii")
    )
    for offset in offsets:
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii"
        )
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


def _receipt_base(
    profile: str, strict: bool, requirements: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "profile": profile,
        "strict": strict,
        "platform": {
            "system": platform.system().lower(),
            "machine": platform.machine().lower(),
            "python": platform.python_version(),
        },
        "requirements": requirements,
    }


def receipt_exit_code(receipt: dict[str, Any]) -> int:
    if receipt.get("status") == "pass":
        return 0
    if receipt.get("status") == "unavailable" and not receipt.get("strict"):
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        receipt = run_profile(
            arguments.profile, arguments.project_root, strict=arguments.strict
        )
    except ProfileFailure as error:
        receipt = {
            **_receipt_base(arguments.profile, arguments.strict, []),
            "status": "failed",
            "reason": {"code": error.code, "message": error.message},
            "smokes": [],
        }
    except Exception as error:
        receipt = {
            **_receipt_base(arguments.profile, arguments.strict, []),
            "status": "failed",
            "reason": {
                "code": "harness_exception",
                "exception_class": type(error).__name__,
            },
            "smokes": [],
        }
    rendered = json.dumps(
        receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    sys.stdout.buffer.write((rendered + "\n").encode("ascii"))
    sys.stdout.buffer.flush()
    return receipt_exit_code(receipt)


if __name__ == "__main__":
    raise SystemExit(main())
