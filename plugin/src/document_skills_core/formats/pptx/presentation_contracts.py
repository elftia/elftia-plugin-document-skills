"""Pinned consumer for the owner-published presentation contract package.

The schema owner is @elftia/presentation-contracts. This module does not copy
or privately extend those schemas: it verifies a caller-supplied package root
against the pinned manifest and then validates values through the JSON Schemas
in that package.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata
from typing import Any, Literal, Mapping, Sequence

from jsonschema import Draft202012Validator


ContractKind = Literal["deck-ir", "semantic-slots", "template-contract"]
PresentationIdKind = Literal["deck", "slide", "object"]

_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PRESENTATION_ID_PATTERN = re.compile(r"^(deck|slide|object)_[0-9a-f]{32}$")
_STABLE_ID_VERSION = "elftia.presentation-id.v1"


@dataclass(frozen=True)
class PresentationContractPin:
    """The exact owner-package identity accepted by this consumer."""

    package: str
    package_version: str
    manifest_sha256: str
    deck_ir_schema_version: str
    semantic_slot_schema_version: str
    template_contract_schema_version: str
    artifact_paths: tuple[str, ...]


PRESENTATION_CONTRACT_V1_PIN = PresentationContractPin(
    package="@elftia/presentation-contracts",
    package_version="1.0.0",
    manifest_sha256=(
        "sha256:78989d9891c80a3f89ad25d7d31e4a431737131226df4494fc14dee1bfe3215a"
    ),
    deck_ir_schema_version="1.0.0",
    semantic_slot_schema_version="1.0.0",
    template_contract_schema_version="1.0.0",
    artifact_paths=(
        "fixtures/v1/deck-ir.valid.json",
        "fixtures/v1/semantic-slots.valid.json",
        "fixtures/v1/stable-id-vectors.json",
        "fixtures/v1/template-contract.not-evaluated.json",
        "schemas/v1/deck-ir.schema.json",
        "schemas/v1/semantic-slots.schema.json",
        "schemas/v1/template-contract.schema.json",
    ),
)


class PresentationContractConsumerError(ValueError):
    """Fail-closed presentation contract consumer error."""

    def __init__(self, code: str, message: str, *, issues: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.issues = tuple(issues)


def _digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PresentationContractConsumerError(
            "PRESENTATION_CONTRACT_INVALID_PACKAGE",
            f"presentation contract JSON is unreadable: {path.name}",
        ) from error


def _canonical_json(value: Any) -> str:
    if value is None or isinstance(value, (bool, int, float, str)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if isinstance(value, list):
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=lambda item: item.encode("utf-8"))
        members = (
            json.dumps(key, ensure_ascii=False, separators=(",", ":"))
            + ":"
            + _canonical_json(value[key])
            for key in keys
        )
        return "{" + ",".join(members) + "}"
    raise PresentationContractConsumerError(
        "PRESENTATION_CONTRACT_INVALID",
        f"Deck IR contains a non-JSON value: {type(value).__name__}",
    )


def _canonical_deck_hash(value: Mapping[str, Any]) -> str:
    content = {key: member for key, member in value.items() if key != "contentHash"}
    return _digest_bytes(_canonical_json(content).encode("utf-8"))


def _canonical_id_part(value: str, label: str, *, reject_array_index: bool = False) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise PresentationContractConsumerError(
            "PRESENTATION_CONTRACT_INVALID",
            f"{label} must be a non-empty, trimmed string",
        )
    if unicodedata.normalize("NFKC", value) != value:
        raise PresentationContractConsumerError(
            "PRESENTATION_CONTRACT_INVALID",
            f"{label} must already be NFKC-normalized",
        )
    if "\x00" in value or "\r" in value or "\n" in value:
        raise PresentationContractConsumerError(
            "PRESENTATION_CONTRACT_INVALID",
            f"{label} must not contain NUL or newline characters",
        )
    if reject_array_index and value.isdecimal():
        raise PresentationContractConsumerError(
            "PRESENTATION_CONTRACT_INVALID",
            f"{label} must be a semantic key, not an array index",
        )
    return value


def _derive_id(kind: PresentationIdKind, parts: Sequence[str]) -> str:
    frames = [_STABLE_ID_VERSION, kind, *parts]
    framed = "|".join(f"{len(value.encode('utf-8'))}:{value}" for value in frames)
    return f"{kind}_{hashlib.sha256(framed.encode('utf-8')).hexdigest()[:32]}"


def _require_id(value: str, kind: PresentationIdKind) -> str:
    if not _PRESENTATION_ID_PATTERN.fullmatch(value) or not value.startswith(f"{kind}_"):
        raise PresentationContractConsumerError(
            "PRESENTATION_CONTRACT_INVALID",
            f"expected a stable {kind} id",
        )
    return value


def _resolve_member(root: Path, relative: str) -> Path:
    normalized = unicodedata.normalize("NFKC", relative)
    posix = PurePosixPath(relative)
    if (
        normalized != relative
        or "\\" in relative
        or posix.is_absolute()
        or not posix.parts
        or any(part in {"", ".", ".."} for part in posix.parts)
        or posix.as_posix() != relative
    ):
        raise PresentationContractConsumerError(
            "PRESENTATION_CONTRACT_INVALID_PACKAGE",
            f"unsafe presentation contract artifact path: {relative}",
        )
    candidate = root.joinpath(*posix.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise PresentationContractConsumerError(
            "PRESENTATION_CONTRACT_INVALID_PACKAGE",
            f"presentation contract artifact escapes or is missing: {relative}",
        ) from error
    current = root
    for part in posix.parts:
        current = current / part
        if current.is_symlink():
            raise PresentationContractConsumerError(
                "PRESENTATION_CONTRACT_INVALID_PACKAGE",
                f"presentation contract artifact path contains a symlink: {relative}",
            )
    if not resolved.is_file():
        raise PresentationContractConsumerError(
            "PRESENTATION_CONTRACT_INVALID_PACKAGE",
            f"presentation contract artifact is not a regular file: {relative}",
        )
    return resolved


class PresentationContractConsumer:
    """Deep consumer module for schema, hash, and stable-ID conformance."""

    def __init__(
        self,
        *,
        root: Path,
        pin: PresentationContractPin,
        manifest: Mapping[str, Any],
        validators: Mapping[ContractKind, Draft202012Validator],
    ) -> None:
        self.root = root
        self.pin = pin
        self.manifest = dict(manifest)
        self._validators = dict(validators)

    @classmethod
    def open(
        cls,
        root: Path,
        *,
        pin: PresentationContractPin = PRESENTATION_CONTRACT_V1_PIN,
    ) -> "PresentationContractConsumer":
        """Verify an owner package and return its schema consumer."""

        try:
            resolved_root = root.resolve(strict=True)
        except OSError as error:
            raise PresentationContractConsumerError(
                "PRESENTATION_CONTRACT_INVALID_PACKAGE",
                "presentation contract package root does not exist",
            ) from error
        if not resolved_root.is_dir():
            raise PresentationContractConsumerError(
                "PRESENTATION_CONTRACT_INVALID_PACKAGE",
                "presentation contract package root is not a directory",
            )

        manifest_path = _resolve_member(resolved_root, "schemas/schema-manifest.json")
        manifest_bytes = manifest_path.read_bytes()
        actual_manifest_hash = _digest_bytes(manifest_bytes)
        if actual_manifest_hash != pin.manifest_sha256:
            raise PresentationContractConsumerError(
                "PRESENTATION_CONTRACT_PIN_MISMATCH",
                "presentation contract manifest does not match the pinned owner artifact",
            )
        manifest = _load_json(manifest_path)
        if not isinstance(manifest, dict):
            raise PresentationContractConsumerError(
                "PRESENTATION_CONTRACT_INVALID_PACKAGE",
                "presentation contract manifest must be an object",
            )

        expected_identity = {
            "package": pin.package,
            "packageVersion": pin.package_version,
            "deckIrSchemaVersion": pin.deck_ir_schema_version,
            "semanticSlotSchemaVersion": pin.semantic_slot_schema_version,
            "templateContractSchemaVersion": pin.template_contract_schema_version,
            "migrationPolicy": "explicit-only",
        }
        for key, expected in expected_identity.items():
            if manifest.get(key) != expected:
                raise PresentationContractConsumerError(
                    "PRESENTATION_CONTRACT_PIN_MISMATCH",
                    f"presentation contract manifest {key} does not match the pin",
                )

        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise PresentationContractConsumerError(
                "PRESENTATION_CONTRACT_INVALID_PACKAGE",
                "presentation contract manifest artifacts must be an array",
            )
        records: dict[str, str] = {}
        folded_paths: set[str] = set()
        for record in artifacts:
            if not isinstance(record, dict):
                raise PresentationContractConsumerError(
                    "PRESENTATION_CONTRACT_INVALID_PACKAGE",
                    "presentation contract artifact record must be an object",
                )
            relative = record.get("path")
            expected_hash = record.get("sha256")
            if not isinstance(relative, str) or not isinstance(expected_hash, str):
                raise PresentationContractConsumerError(
                    "PRESENTATION_CONTRACT_INVALID_PACKAGE",
                    "presentation contract artifact record requires path and sha256",
                )
            if not _SHA256_PATTERN.fullmatch(expected_hash):
                raise PresentationContractConsumerError(
                    "PRESENTATION_CONTRACT_INVALID_PACKAGE",
                    f"invalid presentation contract artifact digest: {relative}",
                )
            folded = unicodedata.normalize("NFKC", relative).casefold()
            if relative in records or folded in folded_paths:
                raise PresentationContractConsumerError(
                    "PRESENTATION_CONTRACT_INVALID_PACKAGE",
                    f"duplicate presentation contract artifact path: {relative}",
                )
            path = _resolve_member(resolved_root, relative)
            if _digest_bytes(path.read_bytes()) != expected_hash:
                raise PresentationContractConsumerError(
                    "PRESENTATION_CONTRACT_HASH_MISMATCH",
                    f"presentation contract artifact hash mismatch: {relative}",
                )
            records[relative] = expected_hash
            folded_paths.add(folded)

        if tuple(sorted(records)) != tuple(sorted(pin.artifact_paths)):
            raise PresentationContractConsumerError(
                "PRESENTATION_CONTRACT_PIN_MISMATCH",
                "presentation contract artifact set does not match the pin",
            )

        schema_paths: dict[ContractKind, str] = {
            "deck-ir": "schemas/v1/deck-ir.schema.json",
            "semantic-slots": "schemas/v1/semantic-slots.schema.json",
            "template-contract": "schemas/v1/template-contract.schema.json",
        }
        validators: dict[ContractKind, Draft202012Validator] = {}
        for kind, relative in schema_paths.items():
            schema = _load_json(_resolve_member(resolved_root, relative))
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as error:
                raise PresentationContractConsumerError(
                    "PRESENTATION_CONTRACT_INVALID_PACKAGE",
                    f"invalid presentation contract schema: {relative}",
                ) from error
            validators[kind] = Draft202012Validator(schema)

        consumer = cls(
            root=resolved_root,
            pin=pin,
            manifest=manifest,
            validators=validators,
        )
        consumer._verify_owner_goldens()
        return consumer

    def validate(self, kind: ContractKind, value: Any) -> dict[str, Any]:
        """Validate one supported owner contract and its cross-field invariants."""

        expected_versions = {
            "deck-ir": self.pin.deck_ir_schema_version,
            "semantic-slots": self.pin.semantic_slot_schema_version,
            "template-contract": self.pin.template_contract_schema_version,
        }
        if not isinstance(value, dict):
            raise PresentationContractConsumerError(
                "PRESENTATION_CONTRACT_INVALID",
                f"{kind} must be an object",
            )
        if value.get("schemaVersion") != expected_versions[kind]:
            raise PresentationContractConsumerError(
                "PRESENTATION_CONTRACT_UNSUPPORTED_VERSION",
                f"unsupported {kind} schema version: {value.get('schemaVersion')}",
            )
        errors = sorted(
            self._validators[kind].iter_errors(value),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if errors:
            issues = tuple(
                f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: "
                f"{error.message}"
                for error in errors
            )
            raise PresentationContractConsumerError(
                "PRESENTATION_CONTRACT_INVALID",
                f"{kind} is invalid: {'; '.join(issues)}",
                issues=issues,
            )
        if kind == "deck-ir":
            self._validate_deck_invariants(value)
        elif kind == "semantic-slots":
            self._validate_slot_invariants(value)
        return value

    @staticmethod
    def stable_deck_id(
        *, namespace: str, source_template_id: str, source_template_version: str
    ) -> str:
        return _derive_id(
            "deck",
            [
                _canonical_id_part(namespace, "namespace"),
                _canonical_id_part(source_template_id, "sourceTemplateId"),
                _canonical_id_part(source_template_version, "sourceTemplateVersion"),
            ],
        )

    @staticmethod
    def stable_slide_id(
        *, deck_id: str, source_template_id: str, semantic_key: str
    ) -> str:
        return _derive_id(
            "slide",
            [
                _require_id(deck_id, "deck"),
                _canonical_id_part(source_template_id, "sourceTemplateId"),
                _canonical_id_part(semantic_key, "semanticKey", reject_array_index=True),
            ],
        )

    @staticmethod
    def stable_object_id(*, slide_id: str, semantic_key: str) -> str:
        return _derive_id(
            "object",
            [
                _require_id(slide_id, "slide"),
                _canonical_id_part(semantic_key, "semanticKey", reject_array_index=True),
            ],
        )

    @staticmethod
    def deck_content_hash(value: Mapping[str, Any]) -> str:
        """Build the owner-defined canonical Deck IR content hash."""

        return _canonical_deck_hash(value)

    def summary(self) -> dict[str, Any]:
        vectors = _load_json(
            _resolve_member(self.root, "fixtures/v1/stable-id-vectors.json")
        )
        deck_id = self.stable_deck_id(
            namespace=vectors["deck"]["input"]["namespace"],
            source_template_id=vectors["deck"]["input"]["sourceTemplateId"],
            source_template_version=vectors["deck"]["input"]["sourceTemplateVersion"],
        )
        slide_id = self.stable_slide_id(
            deck_id=deck_id,
            source_template_id=vectors["slide"]["input"]["sourceTemplateId"],
            semantic_key=vectors["slide"]["input"]["semanticKey"],
        )
        object_id = self.stable_object_id(
            slide_id=slide_id,
            semantic_key=vectors["object"]["input"]["semanticKey"],
        )
        deck = _load_json(_resolve_member(self.root, "fixtures/v1/deck-ir.valid.json"))
        template = _load_json(
            _resolve_member(
                self.root, "fixtures/v1/template-contract.not-evaluated.json"
            )
        )
        return {
            "consumer": "document-skills",
            "package": self.pin.package,
            "packageVersion": self.pin.package_version,
            "manifestSha256": self.pin.manifest_sha256,
            "artifactCount": len(self.pin.artifact_paths),
            "schemaVersions": {
                "deckIr": self.pin.deck_ir_schema_version,
                "semanticSlots": self.pin.semantic_slot_schema_version,
                "templateContract": self.pin.template_contract_schema_version,
            },
            "stableIds": {"deck": deck_id, "slide": slide_id, "object": object_id},
            "deckContentHash": deck["contentHash"],
            "licenseStatus": template["licenseStatus"],
        }

    def _verify_owner_goldens(self) -> None:
        deck = _load_json(_resolve_member(self.root, "fixtures/v1/deck-ir.valid.json"))
        slots = _load_json(
            _resolve_member(self.root, "fixtures/v1/semantic-slots.valid.json")
        )
        template = _load_json(
            _resolve_member(
                self.root, "fixtures/v1/template-contract.not-evaluated.json"
            )
        )
        self.validate("deck-ir", deck)
        self.validate("semantic-slots", slots)
        self.validate("template-contract", template)

        vectors = _load_json(
            _resolve_member(self.root, "fixtures/v1/stable-id-vectors.json")
        )
        deck_id = self.stable_deck_id(
            namespace=vectors["deck"]["input"]["namespace"],
            source_template_id=vectors["deck"]["input"]["sourceTemplateId"],
            source_template_version=vectors["deck"]["input"]["sourceTemplateVersion"],
        )
        slide_id = self.stable_slide_id(
            deck_id=deck_id,
            source_template_id=vectors["slide"]["input"]["sourceTemplateId"],
            semantic_key=vectors["slide"]["input"]["semanticKey"],
        )
        object_id = self.stable_object_id(
            slide_id=slide_id,
            semantic_key=vectors["object"]["input"]["semanticKey"],
        )
        actual = {"deck": deck_id, "slide": slide_id, "object": object_id}
        expected = {kind: vectors[kind]["expected"] for kind in actual}
        if actual != expected:
            raise PresentationContractConsumerError(
                "PRESENTATION_CONTRACT_PIN_MISMATCH",
                "presentation contract stable-ID vectors do not match the consumer",
            )

    @staticmethod
    def _validate_deck_invariants(value: Mapping[str, Any]) -> None:
        expected_hash = _canonical_deck_hash(value)
        if value.get("contentHash") != expected_hash:
            raise PresentationContractConsumerError(
                "PRESENTATION_CONTRACT_HASH_MISMATCH",
                "Deck IR contentHash does not match canonical content",
            )
        canvas_ids = {profile["id"] for profile in value["canvasProfiles"]}
        slide_ids: set[str] = set()
        object_ids: set[str] = set()
        for slide in value["slides"]:
            slide_id = slide["slideId"]
            if slide_id in slide_ids:
                raise PresentationContractConsumerError(
                    "PRESENTATION_CONTRACT_INVALID",
                    f"Deck IR contains duplicate slide id: {slide_id}",
                )
            if slide["canvasProfileId"] not in canvas_ids:
                raise PresentationContractConsumerError(
                    "PRESENTATION_CONTRACT_INVALID",
                    f"Deck IR references unknown canvas profile: {slide['canvasProfileId']}",
                )
            slide_ids.add(slide_id)
            for item in slide["objects"]:
                object_id = item["objectId"]
                if object_id in object_ids:
                    raise PresentationContractConsumerError(
                        "PRESENTATION_CONTRACT_INVALID",
                        f"Deck IR contains duplicate object id: {object_id}",
                    )
                object_ids.add(object_id)

    @staticmethod
    def _validate_slot_invariants(value: Mapping[str, Any]) -> None:
        slot_ids: set[str] = set()
        object_ids: set[str] = set()
        for slot in value["slots"]:
            slot_id = slot["slotId"]
            object_id = slot["sourceObjectId"]
            if slot_id in slot_ids:
                raise PresentationContractConsumerError(
                    "PRESENTATION_CONTRACT_INVALID",
                    f"Semantic Slot set contains duplicate slot id: {slot_id}",
                )
            if object_id in object_ids:
                raise PresentationContractConsumerError(
                    "PRESENTATION_CONTRACT_INVALID",
                    f"Semantic Slot set contains duplicate source object id: {object_id}",
                )
            slot_ids.add(slot_id)
            object_ids.add(object_id)


__all__ = [
    "PRESENTATION_CONTRACT_V1_PIN",
    "PresentationContractConsumer",
    "PresentationContractConsumerError",
    "PresentationContractPin",
]
