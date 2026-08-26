"""Directory-level no-replace publication used by scene bundles."""

import hashlib
import json
from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.core.io.directory_promotion import atomic_publish_directory
from document_skills_core.core.io.parent_anchor import DestinationParentAnchor
from document_skills_core.core.io.parent_anchor_types import ParentSafetyError


def _candidate(root: Path) -> Path:
    candidate = root / "candidate"
    (candidate / "assets").mkdir(parents=True)
    (candidate / "assets" / "image.bin").write_bytes(b"asset")
    manifest = json.dumps(
        {"members": ["assets/image.bin"]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    (candidate / "manifest.json").write_bytes(manifest)
    return candidate


def test_atomic_directory_publication_installs_manifest_and_tree(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    expected = hashlib.sha256((candidate / "manifest.json").read_bytes()).hexdigest()
    destination = tmp_path / "published"

    outcome = atomic_publish_directory(
        candidate,
        destination,
        expected_manifest_sha256=expected,
    )

    assert outcome.state == "committed_clean"
    assert Path(outcome.path) == destination / "manifest.json"
    assert (destination / "assets" / "image.bin").read_bytes() == b"asset"
    assert not list(tmp_path.glob(".published.elftia-dir-stage-*"))


def test_atomic_directory_publication_never_replaces_existing_destination(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    destination = tmp_path / "published"
    destination.mkdir()
    sentinel = destination / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(DocumentSkillsError) as error:
        atomic_publish_directory(candidate, destination)

    assert error.value.code.value == "DS_PATH_UNSAFE"
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (destination / "manifest.json").exists()


def test_atomic_directory_publication_rejects_manifest_drift(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    destination = tmp_path / "published"

    with pytest.raises(DocumentSkillsError) as error:
        atomic_publish_directory(
            candidate,
            destination,
            expected_manifest_sha256="0" * 64,
        )

    assert error.value.code.value == "DS_VALIDATION_FAILED"
    assert not destination.exists()


def test_atomic_directory_publication_rejects_redirected_member(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    redirected = candidate / "assets" / "redirected.bin"
    target = tmp_path / "outside.bin"
    target.write_bytes(b"outside")
    try:
        redirected.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlink unavailable: {type(error).__name__}")

    with pytest.raises(DocumentSkillsError) as error:
        atomic_publish_directory(candidate, tmp_path / "published")

    assert error.value.code.value == "DS_PATH_UNSAFE"
    assert not (tmp_path / "published").exists()


def test_atomic_directory_publication_rejects_broken_symlink_destination(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    destination = tmp_path / "published"
    try:
        destination.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink unavailable: {type(error).__name__}")

    with pytest.raises(DocumentSkillsError) as captured:
        atomic_publish_directory(candidate, destination)

    assert captured.value.code.value == "DS_PATH_UNSAFE"
    assert destination.is_symlink()
    assert not list(tmp_path.glob(".published.elftia-dir-stage-*"))


def test_parent_identity_failure_before_publish_cleans_only_owned_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate(tmp_path)
    candidate_hash = hashlib.sha256(
        (candidate / "assets" / "image.bin").read_bytes()
    ).hexdigest()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.bin"
    sentinel.write_bytes(b"outside")
    outside_hash = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    destination = tmp_path / "published"
    original_assert = DestinationParentAnchor.assert_bound

    def fail_before_publish(self: DestinationParentAnchor, phase: str) -> Path:
        if phase == "directory_publish_before":
            raise ParentSafetyError(
                "destination_parent_identity_changed",
                phase=phase,
                original_path=self.original_path,
                current_path=self.current_path(),
            )
        return original_assert(self, phase)

    monkeypatch.setattr(DestinationParentAnchor, "assert_bound", fail_before_publish)
    with pytest.raises(DocumentSkillsError) as captured:
        atomic_publish_directory(candidate, destination)

    assert captured.value.code.value == "DS_VALIDATION_FAILED"
    assert captured.value.details["parent_phase"] == "directory_publish_before"
    assert not destination.exists()
    assert not list(tmp_path.glob(".published.elftia-dir-stage-*"))
    assert hashlib.sha256(
        (candidate / "assets" / "image.bin").read_bytes()
    ).hexdigest() == candidate_hash
    assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == outside_hash
