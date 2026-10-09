"""Hard-storage quota contract and final-tree regression tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import (
    DocumentSkillsError,
    ErrorCode,
)
from document_skills_core.providers.libreoffice.quota import (
    HardQuotaCapability,
    _UnsupportedHardQuotaBackend,
    capture_directory_identity,
    hard_quota_capability,
    require_hard_quota_backend,
    validate_final_quota_tree,
)
from document_skills_core.providers.libreoffice.runner import LibreOfficeRunner


def _private_tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "quota-root"
    output = root / "output"
    profile = root / "profile"
    output.mkdir(parents=True)
    profile.mkdir()
    return root, output


def _validate(
    root: Path,
    output: Path,
    *,
    byte_limit: int = 16 * 1024,
    entry_limit: int = 32,
):
    return validate_final_quota_tree(
        root=root,
        root_identity=capture_directory_identity(root),
        output_dir=output,
        output_identity=capture_directory_identity(output),
        expected_name="result.pdf",
        byte_limit=byte_limit,
        entry_limit=entry_limit,
    )


def test_unsupported_capability_truthfully_reports_no_hard_quota() -> None:
    capability = hard_quota_capability(_UnsupportedHardQuotaBackend())

    assert capability.backend_id == "none"
    assert capability.supported is False
    assert capability.reason_category == "hard_quota_backend_unavailable"
    assert capability.aggregate_byte_limit is False
    assert capability.entry_count_limit is False
    assert capability.private_namespace is False
    assert capability.fail_closed_activation is False


def test_default_backend_fails_before_filesystem_side_effect(tmp_path: Path) -> None:
    before = list(tmp_path.iterdir())

    with pytest.raises(DocumentSkillsError) as caught:
        require_hard_quota_backend(_UnsupportedHardQuotaBackend())

    assert caught.value.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert caught.value.details["supported"] is False
    assert caught.value.details["backend"] == "none"
    assert list(tmp_path.iterdir()) == before


def test_one_shot_32_mib_writer_never_launches_or_persists_over_16_kib(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from document_skills_core.providers.libreoffice import output as output_module

    monkeypatch.setitem(output_module.OUTPUT_LIMITS, "pdf", 16 * 1024)
    output = tmp_path / "output"
    output.mkdir()
    output_identity = capture_directory_identity(output)
    input_path = tmp_path / "input.docx"
    input_path.write_bytes(b"input")
    executable = tmp_path / "soffice.exe"
    executable.write_bytes(b"placeholder")
    calls = 0

    class OneShotWriter:
        def run(self, _provider_id, _executable, args, **_kwargs):
            nonlocal calls
            calls += 1
            child_output = Path(args[args.index("--outdir") + 1]) / "input.pdf"
            child_output.write_bytes(b"x" * (32 * 1024 * 1024))
            raise AssertionError("writer must be gated before its one-shot write")

    runner = LibreOfficeRunner(
        project_root,
        executable=executable,
        runner=OneShotWriter(),
        quota_backend=_UnsupportedHardQuotaBackend(),
    )

    with pytest.raises(DocumentSkillsError) as caught:
        runner.convert(input_path, "pdf", output, timeout_seconds=30.0)

    assert caught.value.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert calls == 0
    assert capture_directory_identity(output) == output_identity
    assert list(output.iterdir()) == []
    assert sum(item.stat().st_size for item in output.iterdir()) == 0


def test_incomplete_backend_claim_cannot_pass_launch_gate() -> None:
    class PerFileOnlyBackend:
        def capability(self):
            return HardQuotaCapability(
                backend_id="rlimit-fsize",
                platform="posix",
                reason_category="per_file_only",
                reason="RLIMIT_FSIZE cannot enforce an aggregate tree limit.",
                aggregate_byte_limit=False,
                entry_count_limit=False,
                private_namespace=True,
                fail_closed_activation=True,
            )

        def open(self, **_kwargs):
            raise AssertionError("incomplete backend must never be activated")

    with pytest.raises(DocumentSkillsError) as caught:
        require_hard_quota_backend(PerFileOnlyBackend())

    assert caught.value.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert caught.value.details["backend"] == "rlimit-fsize"
    assert caught.value.details["guarantees"]["aggregate_byte_limit"] is False


def test_final_tree_reports_exact_identity_count_and_total(tmp_path: Path) -> None:
    root, output = _private_tree(tmp_path)
    payload = b"%PDF-1.7"
    profile_payload = b"profile"
    (output / "result.pdf").write_bytes(payload)
    (root / "profile" / "registrymodifications.xcu").write_bytes(profile_payload)

    snapshot = _validate(root, output)

    assert snapshot.root_identity == capture_directory_identity(root)
    assert snapshot.output_identity == capture_directory_identity(output)
    assert snapshot.entry_count == 4
    assert snapshot.total_bytes == len(payload) + len(profile_payload)
    assert snapshot.output_bytes == len(payload)


def test_final_tree_rejects_one_32_mib_write_for_16_kib_limit(
    tmp_path: Path,
) -> None:
    root, output = _private_tree(tmp_path)
    (output / "result.pdf").write_bytes(b"x" * (32 * 1024 * 1024))

    with pytest.raises(DocumentSkillsError) as caught:
        _validate(root, output)

    assert caught.value.code == ErrorCode.PROVIDER_FAILED
    assert caught.value.details["byte_limit"] == 16 * 1024
    assert caught.value.details["total_bytes"] == 32 * 1024 * 1024


def test_final_tree_counts_temporary_and_multiple_files_aggregately(
    tmp_path: Path,
) -> None:
    root, output = _private_tree(tmp_path)
    (output / "result.pdf").write_bytes(b"x" * 9_000)
    (root / "profile" / "temporary.bin").write_bytes(b"y" * 9_000)

    with pytest.raises(DocumentSkillsError) as caught:
        _validate(root, output)

    assert caught.value.code == ErrorCode.PROVIDER_FAILED
    assert caught.value.details["total_bytes"] == 18_000


def test_final_output_directory_rejects_extra_file(tmp_path: Path) -> None:
    root, output = _private_tree(tmp_path)
    (output / "result.pdf").write_bytes(b"pdf")
    (output / "partial.tmp").write_bytes(b"tmp")

    with pytest.raises(DocumentSkillsError) as caught:
        _validate(root, output)

    assert caught.value.code == ErrorCode.PROVIDER_FAILED
    assert caught.value.details["output_entry_count"] == 2


def test_final_output_directory_rejects_subdirectory(tmp_path: Path) -> None:
    root, output = _private_tree(tmp_path)
    (output / "result.pdf").write_bytes(b"pdf")
    (output / "nested").mkdir()

    with pytest.raises(DocumentSkillsError) as caught:
        _validate(root, output)

    assert caught.value.code == ErrorCode.PROVIDER_FAILED
    assert "subdirectory" in str(caught.value)


def test_final_tree_rejects_entry_flood(tmp_path: Path) -> None:
    root, output = _private_tree(tmp_path)
    (output / "result.pdf").write_bytes(b"pdf")
    for index in range(8):
        (root / "profile" / f"entry-{index}.tmp").touch()

    with pytest.raises(DocumentSkillsError) as caught:
        _validate(root, output, entry_limit=6)

    assert caught.value.code == ErrorCode.PROVIDER_FAILED
    assert caught.value.details["entry_count"] == 7
    assert caught.value.details["entry_limit"] == 6


def test_final_tree_rejects_symlink_without_following_it(tmp_path: Path) -> None:
    root, output = _private_tree(tmp_path)
    (output / "result.pdf").write_bytes(b"pdf")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    try:
        os.symlink(outside, root / "profile" / "redirect")
    except OSError as error:
        pytest.skip(f"symlinks unavailable for this account: {type(error).__name__}")

    with pytest.raises(DocumentSkillsError) as caught:
        _validate(root, output)

    assert caught.value.code == ErrorCode.PROVIDER_FAILED
    assert "redirected" in str(caught.value)


def test_final_tree_rejects_hard_link(tmp_path: Path) -> None:
    root, output = _private_tree(tmp_path)
    expected = output / "result.pdf"
    expected.write_bytes(b"pdf")
    try:
        os.link(expected, root / "profile" / "second-link")
    except OSError as error:
        pytest.skip(f"hard links unavailable: {type(error).__name__}")

    with pytest.raises(DocumentSkillsError) as caught:
        _validate(root, output)

    assert caught.value.code == ErrorCode.PROVIDER_FAILED
    assert "multiply-linked" in str(caught.value)


def test_final_tree_rejects_root_identity_replacement(tmp_path: Path) -> None:
    root, output = _private_tree(tmp_path)
    root_identity = capture_directory_identity(root)
    output_identity = capture_directory_identity(output)
    moved = tmp_path / "moved-root"
    root.rename(moved)
    replacement_output = root / "output"
    replacement_output.mkdir(parents=True)
    (root / "profile").mkdir()
    (replacement_output / "result.pdf").write_bytes(b"pdf")

    with pytest.raises(DocumentSkillsError) as caught:
        validate_final_quota_tree(
            root=root,
            root_identity=root_identity,
            output_dir=replacement_output,
            output_identity=output_identity,
            expected_name="result.pdf",
            byte_limit=16 * 1024,
            entry_limit=32,
        )

    assert caught.value.code == ErrorCode.PROVIDER_FAILED
    assert "root identity changed" in str(caught.value)
