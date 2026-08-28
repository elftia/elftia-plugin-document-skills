"""Independent reopen and semantic gates for pypdf mutations."""

import hashlib
import json
from pathlib import Path
from typing import Any

from pypdf import PasswordType, PdfReader
from pypdf.generic import DictionaryObject, IndirectObject, StreamObject

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.formats.pdf.byte_preflight import preflight_pdf

from .compression_evidence import measure_compression, reopen_visual_evidence
from .operations import (
    _COMPRESSION_POLICIES,
    _PERMISSION_FLAGS,
    _compression_semantic_policy,
)


def validate_encrypted(
    source: Path,
    candidate: Path,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    preflight = preflight_pdf(candidate)
    if not preflight.encrypted:
        _failed("Encrypted candidate does not contain an encryption dictionary.")
    user_reader = PdfReader(candidate, strict=True)
    encryption = user_reader.trailer["/Encrypt"]
    if user_reader.decrypt(arguments["user_password"]) != PasswordType.USER_PASSWORD:
        _failed("Encrypted candidate rejected its user credential.")
    if user_reader.are_permissions_valid is not True:
        _failed("Encrypted candidate permission integrity validation failed.")
    _assert_encryption_dictionary(encryption, arguments)
    _assert_permissions(user_reader, arguments["permissions"])
    _assert_semantics(PdfReader(source, strict=True), user_reader)

    owner_reader = PdfReader(candidate, strict=True)
    if owner_reader.decrypt(arguments["owner_password"]) != PasswordType.OWNER_PASSWORD:
        _failed("Encrypted candidate rejected its owner credential.")
    return _report(
        candidate,
        "operation.encryption",
        {
            "algorithm": "AES-256-R5",
            "encrypted": True,
            "page_count": len(user_reader.pages),
            "permissions_valid": True,
        },
    )


def validate_decrypted(
    source_reader: PdfReader,
    candidate: Path,
) -> dict[str, Any]:
    preflight = preflight_pdf(candidate)
    if preflight.encrypted:
        _failed("Decrypted candidate still contains an encryption dictionary.")
    candidate_reader = PdfReader(candidate, strict=True)
    if candidate_reader.is_encrypted:
        _failed("Decrypted candidate still reports encrypted state.")
    _assert_semantics(source_reader, candidate_reader)
    return _report(
        candidate,
        "operation.decryption",
        {
            "encrypted": False,
            "page_count": len(candidate_reader.pages),
            "semantic_round_trip": True,
        },
    )


def validate_compressed(
    source: Path,
    candidate: Path,
    arguments: dict[str, Any],
    operation_result: dict[str, Any],
) -> dict[str, Any]:
    source_bytes = source.stat().st_size
    candidate_bytes = candidate.stat().st_size
    if candidate_bytes >= source_bytes:
        _failed("Compressed candidate has no positive byte-size evidence.")
    preflight = preflight_pdf(candidate)
    if preflight.encrypted:
        _failed("Compression unexpectedly encrypted the candidate.")
    try:
        source_reader = PdfReader(source, strict=True)
        candidate_reader = PdfReader(candidate, strict=True)
    except Exception:
        _failed("Compressed candidate could not be strictly reopened.")
    mode = arguments["mode"]
    _assert_semantics(
        source_reader,
        candidate_reader,
        allow_image_changes=mode != "lossless",
    )
    measured = measure_compression(source, candidate)
    compression = operation_result.get("compression")
    if not isinstance(compression, dict) or compression.get("evidence") != measured:
        _failed("Compression evidence does not match the reopened artifacts.")
    expected_claims = {
        "mode": mode,
        "before_bytes": source_bytes,
        "after_bytes": candidate_bytes,
        "bytes_saved": source_bytes - candidate_bytes,
        "ratio": round(candidate_bytes / source_bytes, 6),
        "content_streams_recompressed": measured["components"]["stream"][
            "content_changed_count"
        ],
        "duplicate_cleanup": (
            measured["components"]["duplicate"]["after"]["count"]
            < measured["components"]["duplicate"]["before"]["count"]
        ),
        "semantic_policy": _compression_semantic_policy(mode),
    }
    if any(compression.get(key) != value for key, value in expected_claims.items()):
        _failed("Compression report claims do not match the measured artifacts.")
    operation_gate = (
        "operation.lossless-compression"
        if mode == "lossless"
        else "operation.image-compression"
    )
    extra_gates: list[dict[str, Any]] = []
    if mode != "lossless":
        visual_diff = operation_result.get("visual_diff")
        if not isinstance(visual_diff, dict) or not visual_diff.get("images"):
            _failed("Lossy compression is missing decoded-image visual evidence.")
        try:
            reopened_visual = reopen_visual_evidence(
                source_reader,
                candidate_reader,
                mode,
                _COMPRESSION_POLICIES[mode],
            )
        except Exception:
            _failed("Lossy compression visual evidence could not be reopened safely.")
        if visual_diff != reopened_visual:
            _failed("Lossy compression visual evidence does not match the artifacts.")
        if (
            compression.get("images_recompressed")
            != reopened_visual["images_recompressed"]
            or compression.get("images_downsampled")
            != reopened_visual["images_downsampled"]
        ):
            _failed("Compression image claims do not match the visual evidence.")
        extra_gates.append(
            gate_record(
                "visual.image-xobject-diff",
                "pass",
                evidence=reopened_visual,
            )
        )
    elif (
        compression.get("images_recompressed") != 0
        or compression.get("images_downsampled") != 0
    ):
        _failed("Lossless compression reported unsupported image changes.")
    return _report(
        candidate,
        operation_gate,
        {
            "mode": mode,
            "before_bytes": source_bytes,
            "after_bytes": candidate_bytes,
            "bytes_saved": source_bytes - candidate_bytes,
            "semantic_round_trip": True,
            "compression_evidence": measured,
        },
        extra_gates=extra_gates,
    )


def _assert_encryption_dictionary(
    encryption: Any,
    arguments: dict[str, Any],
) -> None:
    if (
        encryption.get("/V") != 5
        or encryption.get("/R") != 5
        or encryption.get("/Length") != 256
        or encryption["/CF"]["/StdCF"].get("/CFM") != "/AESV3"
    ):
        _failed("Encrypted candidate is not AES-256-R5.")
    if encryption.get("/EncryptMetadata", True) is not arguments["encrypt_metadata"]:
        _failed("Encrypted candidate metadata policy does not match the request.")


def _assert_permissions(reader: PdfReader, requested: list[str]) -> None:
    permissions = reader.user_access_permissions
    if permissions is None:
        _failed("Encrypted candidate did not expose verified permissions.")
    actual = sorted(
        name
        for name, flag in _PERMISSION_FLAGS.items()
        if permissions & flag == flag
    )
    if actual != requested:
        _failed("Encrypted candidate permissions do not match the request.")


def _assert_semantics(
    source: PdfReader,
    candidate: PdfReader,
    *,
    allow_image_changes: bool = False,
) -> None:
    if _semantic_digest(
        source,
        include_image_identity=not allow_image_changes,
    ) != _semantic_digest(
        candidate,
        include_image_identity=not allow_image_changes,
    ):
        _failed("PDF document semantics changed during provider mutation.")


def _semantic_digest(
    reader: PdfReader,
    *,
    include_image_identity: bool = True,
) -> str:
    pages = []
    for page in reader.pages:
        record = {
            "media_box": [float(value) for value in page.mediabox],
            "crop_box": [float(value) for value in page.cropbox],
            "rotation": int(page.get("/Rotate", 0)),
            "text": page.extract_text() or "",
            "content_sha256": _content_sha256(page),
            "resources": _resource_projection(page.get("/Resources")),
        }
        if include_image_identity:
            record["images"] = _image_identities(page.get("/Resources"))
        pages.append(record)
    metadata = {
        str(key): str(value)
        for key, value in sorted((reader.metadata or {}).items(), key=lambda item: str(item[0]))
    }
    root_metadata = _resolve(reader.root_object.get("/Metadata"))
    xmp_sha256 = (
        hashlib.sha256(root_metadata.get_data()).hexdigest()
        if isinstance(root_metadata, StreamObject)
        else None
    )
    encoded = json.dumps(
        {"metadata": metadata, "xmp_sha256": xmp_sha256, "pages": pages},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _content_sha256(page: Any) -> str:
    contents = page.get_contents()
    payload = contents.get_data() if contents is not None else b""
    return hashlib.sha256(payload).hexdigest()


def _resource_projection(value: Any) -> dict[str, Any]:
    resources = _resolve(value)
    if not isinstance(resources, DictionaryObject):
        return {}
    projected: dict[str, Any] = {}
    for category, raw_entries in sorted(resources.items(), key=lambda item: str(item[0])):
        entries = _resolve(raw_entries)
        if not isinstance(entries, DictionaryObject):
            projected[str(category)] = _simple_value(entries)
            continue
        projected[str(category)] = {
            str(name): _resource_descriptor(_resolve(resource))
            for name, resource in sorted(entries.items(), key=lambda item: str(item[0]))
        }
    return projected


def _resource_descriptor(value: Any) -> dict[str, Any]:
    if not isinstance(value, DictionaryObject):
        return {"value": _simple_value(value)}
    subtype = str(value.get("/Subtype", ""))
    if subtype == "/Image":
        return {
            "/Type": str(value.get("/Type", "")),
            "/Subtype": subtype,
        }
    excluded = {"/Length", "/Filter", "/DecodeParms"}
    descriptor = {
        str(key): simple
        for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
        if str(key) not in excluded
        if (simple := _simple_value(item)) is not None
    }
    if isinstance(value, StreamObject) and subtype != "/Image":
        descriptor["decoded_stream_sha256"] = hashlib.sha256(
            value.get_data()
        ).hexdigest()
    return descriptor


def _image_identities(value: Any) -> list[dict[str, Any]]:
    resources = _resolve(value)
    if not isinstance(resources, DictionaryObject):
        return []
    xobjects = _resolve(resources.get("/XObject"))
    if not isinstance(xobjects, DictionaryObject):
        return []
    identities: list[dict[str, Any]] = []
    for name, raw_object in sorted(xobjects.items(), key=lambda item: str(item[0])):
        obj = _resolve(raw_object)
        if not isinstance(obj, StreamObject):
            continue
        if obj.get("/Subtype") == "/Image":
            payload = obj._data
            if payload is None:
                payload = b""
            identities.append({
                "name": str(name),
                "width": int(obj.get("/Width", 0)),
                "height": int(obj.get("/Height", 0)),
                "bits_per_component": int(obj.get("/BitsPerComponent", 0)),
                "color_space": str(obj.get("/ColorSpace", "")),
                "encoded_sha256": hashlib.sha256(bytes(payload)).hexdigest(),
            })
        elif obj.get("/Subtype") == "/Form":
            for nested in _image_identities(obj.get("/Resources")):
                identities.append({**nested, "name": f"{name}/{nested['name']}"})
    return identities


def _simple_value(value: Any) -> Any:
    value = _resolve(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        items = [_simple_value(item) for item in value]
        return items if all(item is not None for item in items) else None
    return None


def _resolve(value: Any) -> Any:
    return value.get_object() if isinstance(value, IndirectObject) else value


def _report(
    candidate: Path,
    gate_id: str,
    evidence: dict[str, Any],
    *,
    extra_gates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    identity = {
        "bounded_preflight": True,
        "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "bytes": candidate.stat().st_size,
    }
    gates = [
        gate_record(
            "pdf.byte-format-security",
            "pass",
            evidence=identity,
        ),
        gate_record(gate_id, "pass", evidence=evidence),
    ]
    gates.extend(extra_gates or [])
    gates.append(
        gate_record(
            "visual.render",
            "unavailable",
            required=False,
            evidence={"reason": "No accepted visual-render provider was used."},
            warnings=["Optional visual validation is unavailable."],
        )
    )
    return {"schema_version": "1.0", "status": "pass", "gates": gates}


def _failed(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message)
