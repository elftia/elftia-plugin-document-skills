"""Public-process harness for PDF pipe and workspace failure fixtures."""

import ctypes
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import threading
import time

sys.dont_write_bytecode = True
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from document_skills_core.core.contracts.serialization import render_json_bytes  # noqa: E402
from document_skills_core.core.io import bound_child_directory as bound_child  # noqa: E402
from document_skills_core.public_cli.supervisor import PublicCommandSupervisor  # noqa: E402


_LOCK_MODES = {"workspace-lock-transient", "workspace-lock-permanent"}


class _WorkspaceLockController:
    """Hold the current invocation directory without sharing delete access."""

    def __init__(self, private_root: Path, mode: str) -> None:
        self.private_root = private_root
        self.mode = mode
        self.lock_acquired = False
        self.identity_replacement_blocked = False
        self.cleanup_attempt_count = 0
        self.cleanup_failure_count = 0
        self.controller_error: str | None = None
        self._release = threading.Event()
        self._released = threading.Event()
        self._thread = threading.Thread(target=self._hold_lock, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def release(self) -> None:
        self._release.set()

    def release_after_cleanup_failure(self) -> None:
        self.cleanup_failure_count += 1
        if self.mode == "workspace-lock-transient":
            self.release()
            if not self._released.wait(timeout=2.0):
                self.controller_error = "directory lock did not release"

    def join(self) -> None:
        self._thread.join(timeout=5.0)
        if self._thread.is_alive() and self.controller_error is None:
            self.controller_error = "directory lock controller did not stop"

    def _hold_lock(self) -> None:
        handle: int | None = None
        try:
            deadline = time.monotonic() + 5.0
            while not self.private_root.is_dir():
                if time.monotonic() >= deadline:
                    raise TimeoutError("private workspace was not created")
                time.sleep(0.005)
            displaced = self.private_root.with_name(self.private_root.name + "-probe")
            try:
                self.private_root.rename(displaced)
            except PermissionError:
                self.identity_replacement_blocked = True
            else:
                displaced.rename(self.private_root)
                raise RuntimeError("private workspace identity replacement was allowed")
            handle = _open_directory_without_delete_share(self.private_root)
            self.lock_acquired = True
            self._release.wait(timeout=10.0)
        except BaseException as error:
            self.controller_error = type(error).__name__
        finally:
            if handle is not None:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
            self._released.set()


def _open_directory_without_delete_share(path: Path) -> int:
    from ctypes import wintypes

    function = ctypes.windll.kernel32.CreateFileW
    function.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    function.restype = wintypes.HANDLE
    handle = function(
        str(path),
        0x80000000 | 0x00100000,
        0x1 | 0x2,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError()
    return int(handle)


def main() -> int:
    mode, request = sys.argv[1:3]
    trace_path = Path(sys.argv[3]) if len(sys.argv) == 4 else None
    with TemporaryDirectory() as temporary:
        sandbox = Path(temporary).resolve()
        shutil.copytree(PROJECT_ROOT / "src", sandbox / "src")
        shutil.copytree(PROJECT_ROOT / "schemas", sandbox / "schemas")
        worker = sandbox / "src" / "document_skills_core" / "worker" / "main.py"
        shutil.copy2(worker, worker.with_name("fixture_static_main.py"))
        shutil.copy2(Path(__file__).with_name("worker.py"), worker)
        return _run_case(sandbox, mode, request, trace_path)


def _run_case(
    sandbox: Path,
    mode: str,
    request: str,
    trace_path: Path | None,
) -> int:
    private_root = sandbox / ".document-skills-tmp" / f"invocation-pdf-{mode}"
    controller = (
        _WorkspaceLockController(private_root, mode) if mode in _LOCK_MODES else None
    )
    original_delete_open = bound_child.open_windows_relative_directory_for_delete
    if controller is not None:
        controller.start()

        def observed_delete_open(*args: object, **kwargs: object) -> int:
            controller.cleanup_attempt_count += 1
            try:
                return original_delete_open(*args, **kwargs)
            except PermissionError:
                controller.release_after_cleanup_failure()
                raise

        bound_child.open_windows_relative_directory_for_delete = observed_delete_open
    started = time.monotonic()
    try:
        payload, success = PublicCommandSupervisor(
            sandbox,
            timeout_seconds=0.5 if mode == "hang" else 8.0,
            output_limit=32_768,
            nonce_factory=lambda: f"pdf-{mode}",
        ).run("pdf", ["run", "--request", request])
    finally:
        elapsed_seconds = time.monotonic() - started
        bound_child.open_windows_relative_directory_for_delete = original_delete_open
        root_exists_at_return = private_root.exists()
        residual_entries: list[str] = []
        fixture_cleanup_used = False
        if controller is not None:
            controller.release()
            controller.join()
            if mode == "workspace-lock-transient":
                deadline = time.monotonic() + 1.0
                while private_root.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
            root_exists = private_root.exists()
            if root_exists:
                residual_entries = sorted(path.name for path in private_root.iterdir())
            if private_root.exists():
                private_root.rmdir()
                fixture_cleanup_used = True
            if trace_path is not None:
                trace_path.write_text(
                    json.dumps(
                        {
                            "cleanup_failure_count": controller.cleanup_failure_count,
                            "cleanup_attempt_count": controller.cleanup_attempt_count,
                            "controller_error": controller.controller_error,
                            "fixture_cleanup_used": fixture_cleanup_used,
                            "identity_replacement_blocked": controller.identity_replacement_blocked,
                            "lock_acquired": controller.lock_acquired,
                            "private_root_exists_after_supervisor": (
                                root_exists_at_return
                                if mode == "workspace-lock-permanent"
                                else root_exists
                            ),
                            "residual_entries": residual_entries,
                            "supervisor_elapsed_seconds": elapsed_seconds,
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                    encoding="ascii",
                )
        elif private_root.is_dir():
            # POSIX production keeps the exact empty random leaf because there is
            # no portable object-bound rmdir. This fixture removes only its leaf.
            private_root.rmdir()
    sys.stdout.buffer.write(render_json_bytes(payload))
    failed = payload.get("status") in {
        "failed",
        "fail",
        "invalid_request",
        "unavailable",
    }
    return 0 if success and not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
