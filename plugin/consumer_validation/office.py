"""Safe, bounded Microsoft Office detection and COM open probes."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any


_PROG_IDS = {
    "word": "Word.Application",
    "excel": "Excel.Application",
    "powerpoint": "PowerPoint.Application",
}
_OFFICE_IMAGES = {
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
}
_CLEANUP_CATEGORIES = {
    "cleanup-internal-error",
    "descendant-cleanup-error",
    "descendant-cleanup-incomplete",
    "descendant-enumeration-error",
    "handle-tree-complete",
    "handle-tree-incomplete",
    "taskkill-complete",
    "taskkill-error",
    "taskkill-incomplete",
    "taskkill-nonzero",
    "taskkill-timeout",
}


@dataclass(frozen=True)
class _OfficeProcessObservation:
    """One raw PID snapshot with an explicit image-resolution partition."""

    raw_process_ids: frozenset[int]
    matching_process_ids: frozenset[int]
    nonmatching_process_ids: frozenset[int]
    unresolved_process_ids: frozenset[int]

    def identity_state(self, process_id: int) -> str:
        if process_id not in self.raw_process_ids:
            return "absent"
        if process_id in self.matching_process_ids:
            return "matching"
        if process_id in self.nonmatching_process_ids:
            return "nonmatching"
        return "unresolved"


class _HeldWindowsProcess:
    """An exact process object kept open across validation and termination."""

    def __init__(
        self,
        *,
        process_id: int,
        handle: Any,
        creation_filetime: int,
        image_name: str,
        kernel32: Any,
    ) -> None:
        self.process_id = process_id
        self.handle = handle
        self.creation_filetime = creation_filetime
        self.image_name = image_name
        self._kernel32 = kernel32
        self._closed = False

    def __enter__(self) -> "_HeldWindowsProcess":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def is_running(self) -> bool | None:
        """Return True/False only for an authoritative wait result."""

        try:
            outcome = int(self._kernel32.WaitForSingleObject(self.handle, 0))
        except Exception:
            return None
        if outcome == 258:  # WAIT_TIMEOUT
            return True
        if outcome == 0:  # WAIT_OBJECT_0
            return False
        return None

    def terminate(self) -> bool | None:
        """Terminate this exact object, or report that it already exited."""

        try:
            terminated = bool(self._kernel32.TerminateProcess(self.handle, 1))
        except Exception:
            return None
        if terminated:
            return True
        running = self.is_running()
        if running is False:
            return False
        return None

    def wait(self, timeout_ms: int) -> bool | None:
        """Return True on exit, False on timeout, and None on API failure."""

        try:
            outcome = int(
                self._kernel32.WaitForSingleObject(
                    self.handle,
                    max(int(timeout_ms), 0),
                )
            )
        except Exception:
            return None
        if outcome == 0:
            return True
        if outcome == 258:
            return False
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._kernel32.CloseHandle(self.handle)
        except Exception:
            pass


_POWERSHELL = {
    "word": r"""
$app = New-Object -ComObject Word.Application
$version = [string]$app.Version
Write-OfficeIdentity $app 'word' $version
$app.Visible = $false
$app.DisplayAlerts = 0
$app.AutomationSecurity = 3
$app.Options.UpdateLinksAtOpen = $false
$doc = $app.Documents.Open($env:DS_ARTIFACT, $false, $true)
$doc.Close($false)
$doc = $null
""",
    "excel": r"""
$app = New-Object -ComObject Excel.Application
$version = [string]$app.Version
Write-OfficeIdentity $app 'excel' $version
$app.Visible = $false
$app.DisplayAlerts = $false
$app.AutomationSecurity = 3
$app.AskToUpdateLinks = $false
$book = $app.Workbooks.Open($env:DS_ARTIFACT, 0, $true)
$book.Close($false)
$book = $null
""",
    "powerpoint": r"""
$app = New-Object -ComObject PowerPoint.Application
$version = [string]$app.Version
Write-OfficeIdentity $app 'powerpoint' $version
$app.DisplayAlerts = 1
$app.AutomationSecurity = 3
$deck = $app.Presentations.Open($env:DS_ARTIFACT, $true, $true, $false)
$deck.Close()
$deck = $null
""",
}


def detect_office(application: str) -> dict[str, Any]:
    """Detect one Office application without starting it."""

    prog_id = _PROG_IDS.get(application)
    if prog_id is None:
        raise ValueError(f"Unknown Office application: {application}")
    if os.name != "nt":
        return {"available": False, "application": application, "reason": "not-windows"}
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{prog_id}\\CLSID") as key:
            clsid, _ = winreg.QueryValueEx(key, None)
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{prog_id}\\CurVer") as key:
            current_prog_id, _ = winreg.QueryValueEx(key, None)
        registered_version = str(current_prog_id).rsplit(".", 1)[-1]
        version = (
            f"{registered_version}.0"
            if registered_version.isdigit()
            else registered_version
        )
        return {
            "available": True,
            "application": application,
            "progid": prog_id,
            "clsid": clsid,
            "registered_progid": str(current_prog_id),
            "version": version,
        }
    except OSError:
        return {"available": False, "application": application, "reason": "not-installed"}


def trusted_office_identity(
    application: str,
    detection: dict[str, Any],
) -> dict[str, str]:
    """Project report identity only from the independent detection seam."""

    version = detection.get("version")
    if isinstance(version, str) and version:
        return {
            "application": application,
            "version": version,
            "version_status": "trusted-detection",
        }
    return {
        "application": application,
        "version": "unknown",
        "version_status": "unknown-redacted",
    }


def open_with_office(application: str, artifact: Path, timeout_seconds: float) -> dict[str, Any]:
    """Open read-only in an isolated PowerShell child and never save."""

    if application not in _POWERSHELL:
        raise ValueError(f"Unknown Office application: {application}")
    if os.name != "nt":
        return {"outcome": "unavailable", "category": "not-windows"}
    identity = detect_office(application)
    baseline_office_processes = _office_process_ids(application)
    if baseline_office_processes is None:
        return {
            **identity,
            "outcome": "fail",
            "category": "office-process-observation-unavailable",
        }
    script = _script(application)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    environment = os.environ.copy()
    environment["DS_ARTIFACT"] = str(artifact.resolve(strict=True))
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        cwd=artifact.parent,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        creationflags=creation_flags,
    )
    try:
        stdout, stderr = process.communicate(timeout=max(float(timeout_seconds), 0.1))
    except subprocess.TimeoutExpired as primary_timeout:
        try:
            termination = _terminate_tree(process.pid)
        except Exception:
            termination = {
                "descendants_cleaned": False,
                "cleanup_category": "cleanup-internal-error",
            }
        drain_status = "complete"
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired as drain_timeout:
            drain_status = "timeout"
            stdout = _timeout_stream(drain_timeout.output, primary_timeout.output)
            stderr = _timeout_stream(drain_timeout.stderr, primary_timeout.stderr)
        except (OSError, subprocess.SubprocessError):
            drain_status = "error"
            stdout = _timeout_stream(None, primary_timeout.output)
            stderr = _timeout_stream(None, primary_timeout.stderr)
        termination = _merge_office_cleanup(
            termination,
            _cleanup_owned_office_process(
                application,
                baseline_office_processes,
                stdout,
            ),
        )
        return project_timeout_evidence(
            application=application,
            detection=identity,
            termination=termination,
            drain_status=drain_status,
            stdout=stdout,
            stderr=stderr,
        )
    if not _cleanup_owned_office_process(
        application,
        baseline_office_processes,
        stdout,
    ):
        return {
            **identity,
            "outcome": "fail",
            "category": "office-cleanup-incomplete",
        }
    try:
        payload = _parse_probe_output(stdout, require_result=True)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {
            **identity,
            "outcome": "fail",
            "category": "invalid-probe-output",
            "stdout_sha256": _payload_hash(stdout[:4096]),
        }
    merged = {**identity, **payload}
    if process.returncode != 0:
        return {
            **merged,
            "outcome": "fail",
            "category": str(payload.get("category", "open-rejected")),
            "returncode": process.returncode,
            "stderr_sha256": _payload_hash(stderr[:4096]),
        }
    return merged if merged.get("outcome") == "pass" else {"outcome": "fail", **merged}


def _script(application: str) -> str:
    body = _POWERSHELL[application]
    return rf"""
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class OfficeProbeNative {{
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr windowHandle, out uint processId);
}}
'@
function Write-OfficeIdentity([object]$Application, [string]$ApplicationName, [string]$Version) {{
  [uint32]$officeProcessId = 0
  [int64]$officeWindowHandle = 0
  [int64]$officeProcessStartFiletime = 0
  try {{
    $officeWindowHandle = [int64]$Application.Hwnd
    $windowHandle = [IntPtr]$officeWindowHandle
    if ($windowHandle -ne [IntPtr]::Zero) {{
      [void][OfficeProbeNative]::GetWindowThreadProcessId($windowHandle, [ref]$officeProcessId)
    }}
  }} catch {{}}
  if ($officeProcessId -gt 0) {{
    try {{
      $officeProcess = [Diagnostics.Process]::GetProcessById([int]$officeProcessId)
      try {{ $officeProcessStartFiletime = [int64]$officeProcess.StartTime.ToFileTimeUtc() }} finally {{ $officeProcess.Dispose() }}
    }} catch {{}}
  }}
  @{{ event = 'identity'; application = $ApplicationName; version = $Version; process_id = [int64]$officeProcessId; window_handle = $officeWindowHandle; process_start_filetime = $officeProcessStartFiletime }} | ConvertTo-Json -Compress
}}
$app = $null
$doc = $null
$book = $null
$deck = $null
$version = $null
try {{
{body}
  @{{ outcome = 'pass'; application = '{application}'; version = $version; read_only = $true; saved = $false; macros = 'disabled'; external_updates = 'disabled' }} | ConvertTo-Json -Compress
}} catch {{
  @{{ outcome = 'fail'; application = '{application}'; version = $version; category = 'open-rejected'; exception = $_.Exception.GetType().Name }} | ConvertTo-Json -Compress
  exit 2
}} finally {{
  try {{ if ($doc -ne $null) {{ $doc.Close($false) }} }} catch {{}}
  try {{ if ($book -ne $null) {{ $book.Close($false) }} }} catch {{}}
  try {{ if ($deck -ne $null) {{ $deck.Close() }} }} catch {{}}
  try {{ if ($app -ne $null) {{ $app.Quit() }} }} catch {{}}
  foreach ($item in @($doc, $book, $deck, $app)) {{
    if ($item -ne $null) {{ try {{ [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($item) }} catch {{}} }}
  }}
}}
"""


def _parse_probe_output(payload: bytes, *, require_result: bool = False) -> dict[str, Any]:
    decoded = payload[:4096].decode("utf-8", errors="strict")
    merged: dict[str, Any] = {}
    result_seen = False
    for line in decoded.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if type(record) is not dict:
            raise ValueError("probe-record-is-not-object")
        if record.get("event") == "identity":
            merged.update(
                {
                    key: record[key]
                    for key in ("application", "version")
                    if record.get(key) is not None
                }
            )
            continue
        merged.update(record)
        result_seen = "outcome" in record
    if require_result and not result_seen:
        raise ValueError("probe-result-missing")
    return merged


def _timeout_stream(preferred: Any, fallback: Any) -> bytes:
    value = preferred if preferred is not None else fallback
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace")
    return b""


def _merge_office_cleanup(
    termination: dict[str, Any],
    office_cleaned: bool,
) -> dict[str, Any]:
    if office_cleaned:
        return termination
    merged = dict(termination)
    merged["descendants_cleaned"] = False
    if merged.get("cleanup_category") == "taskkill-complete":
        merged["cleanup_category"] = "descendant-cleanup-incomplete"
    return merged


def _probe_office_identity(
    application: str,
    payload: bytes,
) -> dict[str, Any] | None:
    try:
        decoded = payload[:4096].decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    identities: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for line in decoded.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return None
        if type(record) is not dict:
            return None
        if record.get("event") != "identity":
            if "outcome" in record:
                results.append(record)
            continue
        reported_application = record.get("application")
        version = record.get("version")
        process_id = record.get("process_id")
        window_handle = record.get("window_handle")
        process_start_filetime = record.get("process_start_filetime")
        if (
            reported_application != application
            or type(version) is not str
            or not version
            or len(version) > 128
            or type(process_id) is not int
            or not 0 < process_id <= 0xFFFFFFFF
            or type(window_handle) is not int
            or not 0 < window_handle <= 0x7FFFFFFFFFFFFFFF
            or type(process_start_filetime) is not int
            or not 0 < process_start_filetime <= 0x7FFFFFFFFFFFFFFF
        ):
            return None
        identities.append(
            {
                "application": reported_application,
                "version": version,
                "process_id": process_id,
                "window_handle": window_handle,
                "process_start_filetime": process_start_filetime,
            }
        )
    if not identities or any(identity != identities[0] for identity in identities[1:]):
        return None
    identity = identities[0]
    for result in results:
        if (
            result.get("application") != identity["application"]
            or result.get("version") != identity["version"]
        ):
            return None
    return identity


def _process_image_name(process_id: int) -> str | None:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(32_768)
            length = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(
                handle,
                0,
                buffer,
                ctypes.byref(length),
            ):
                return None
            return Path(buffer.value).name
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def _resolved_process_image_name(
    process_id: int,
    fallback_processes: dict[int, tuple[int, str]] | None = None,
) -> tuple[str | None, dict[int, tuple[int, str]] | None]:
    try:
        image_name = _process_image_name(process_id)
    except Exception:
        image_name = None
    if image_name is not None:
        return image_name, fallback_processes
    if fallback_processes is None:
        try:
            fallback_processes = _snapshot_processes()
        except Exception:
            fallback_processes = {}
    if fallback_processes is None:
        return None, None
    fallback = fallback_processes.get(process_id)
    if fallback is not None and fallback[1]:
        return fallback[1], fallback_processes
    return None, fallback_processes


def _process_start_filetime(process_id: int) -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            return (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def _open_held_office_process(process_id: int) -> _HeldWindowsProcess | None:
    """Open and identify one exact process object with termination authority."""

    handle: Any = None
    kernel32: Any = None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        access = 0x1000 | 0x00100000 | 0x0001
        handle = kernel32.OpenProcess(access, False, process_id)
        if not handle:
            return None
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        buffer = ctypes.create_unicode_buffer(32_768)
        length = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(
            handle,
            0,
            buffer,
            ctypes.byref(length),
        ):
            return None
        creation_filetime = (
            (int(creation.dwHighDateTime) << 32)
            | int(creation.dwLowDateTime)
        )
        image_name = Path(buffer.value).name
        if creation_filetime <= 0 or not image_name:
            return None
        held = _HeldWindowsProcess(
            process_id=process_id,
            handle=handle,
            creation_filetime=creation_filetime,
            image_name=image_name,
            kernel32=kernel32,
        )
        handle = None
        return held
    except Exception:
        return None
    finally:
        if handle and kernel32 is not None:
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass


def _enumerate_process_ids() -> list[int] | None:
    try:
        import ctypes
        from ctypes import wintypes

        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.EnumProcesses.argtypes = [
            ctypes.POINTER(wintypes.DWORD),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        psapi.EnumProcesses.restype = wintypes.BOOL
        capacity = 1_024
        while True:
            process_ids = (wintypes.DWORD * capacity)()
            needed = wintypes.DWORD()
            if not psapi.EnumProcesses(
                process_ids,
                ctypes.sizeof(process_ids),
                ctypes.byref(needed),
            ):
                return None
            count = int(needed.value) // ctypes.sizeof(wintypes.DWORD)
            if count < capacity:
                return [int(process_id) for process_id in process_ids[:count]]
            capacity *= 2
    except Exception:
        return None


def _office_process_ids(
    application: str,
    *,
    priority_process_id: int | None = None,
) -> _OfficeProcessObservation | None:
    process_ids = _enumerate_process_ids()
    if process_ids is None:
        return None
    expected = _OFFICE_IMAGES[application].casefold()
    raw = frozenset(process_ids)
    matching: set[int] = set()
    nonmatching: set[int] = set()
    unresolved: set[int] = set()
    fallback_processes: dict[int, tuple[int, str]] | None = None
    ordered_process_ids = list(raw)
    if priority_process_id in raw:
        ordered_process_ids.remove(priority_process_id)
        ordered_process_ids.insert(0, priority_process_id)
    for process_id in ordered_process_ids:
        image_name, fallback_processes = _resolved_process_image_name(
            process_id,
            fallback_processes,
        )
        if image_name is None:
            unresolved.add(process_id)
        elif image_name.casefold() == expected:
            matching.add(process_id)
        else:
            nonmatching.add(process_id)
    return _OfficeProcessObservation(
        raw_process_ids=raw,
        matching_process_ids=frozenset(matching),
        nonmatching_process_ids=frozenset(nonmatching),
        unresolved_process_ids=frozenset(unresolved),
    )


def _cleanup_owned_office_process(
    application: str,
    baseline: _OfficeProcessObservation | None,
    payload: bytes,
) -> bool:
    if baseline is None:
        return False
    identity = _probe_office_identity(application, payload)
    process_id = None if identity is None else identity["process_id"]
    current = _office_process_ids(
        application,
        priority_process_id=process_id,
    )
    if current is None:
        return False
    if identity is None:
        newly_matching = current.matching_process_ids - baseline.matching_process_ids
        if not newly_matching:
            return True
        if len(newly_matching) != 1:
            return False
        return (
            _wait_for_unbound_office_processes_exit(
                application,
                newly_matching,
                baseline,
            )
            is True
        )
    assert process_id is not None
    baseline_state = baseline.identity_state(process_id)
    if baseline_state in {"nonmatching", "unresolved"}:
        return False
    newly_matching = current.matching_process_ids - baseline.matching_process_ids
    if baseline_state == "matching":
        return not newly_matching
    current_state = current.identity_state(process_id)
    if current_state == "absent":
        return not newly_matching
    if current_state == "unresolved":
        if newly_matching:
            return False
        return _confirm_unresolved_office_process_exit(
            application,
            process_id,
            baseline,
        )
    if current_state != "matching" or process_id not in newly_matching:
        return False
    if newly_matching != {process_id}:
        return False
    natural_exit = _wait_for_office_process_exit(application, process_id)
    if natural_exit is None:
        return False
    if natural_exit:
        return True
    if _process_start_filetime(process_id) != identity["process_start_filetime"]:
        return False
    window_owner = _window_process_id(identity["window_handle"])
    if window_owner != process_id:
        return False
    image_name, _fallback_processes = _resolved_process_image_name(process_id)
    if image_name is None or image_name.casefold() != _OFFICE_IMAGES[application].casefold():
        return False
    visible = _has_visible_window(process_id)
    if visible is not False:
        return False
    pretermination = _office_process_ids(
        application,
        priority_process_id=process_id,
    )
    if pretermination is None:
        return False
    pretermination_state = pretermination.identity_state(process_id)
    if pretermination_state == "absent":
        return True
    if pretermination_state != "matching":
        return False
    target = _open_held_office_process(process_id)
    if target is None:
        return False
    with target:
        if target.creation_filetime != identity["process_start_filetime"]:
            return False
        if target.image_name.casefold() != _OFFICE_IMAGES[application].casefold():
            return False
        running = target.is_running()
        if running is False:
            return True
        if running is not True:
            return False
        try:
            termination = _terminate_tree(process_id, target=target)
        except Exception:
            return False
        return (
            termination.get("descendants_cleaned") is True
            and termination.get("cleanup_category") == "handle-tree-complete"
            and termination.get("target_exited") is True
        )


def _confirm_unresolved_office_process_exit(
    application: str,
    process_id: int,
    baseline: _OfficeProcessObservation,
    timeout_seconds: float = 1.0,
) -> bool:
    """Accept an unresolved candidate only after an independent absence observation."""

    import time

    deadline = time.monotonic() + max(float(timeout_seconds), 0.0)
    while True:
        process_ids = _enumerate_process_ids()
        if process_ids is None:
            return False
        if process_id not in process_ids:
            confirmed = _office_process_ids(
                application,
                priority_process_id=process_id,
            )
            return (
                confirmed is not None
                and confirmed.identity_state(process_id) == "absent"
                and not (
                    confirmed.matching_process_ids - baseline.matching_process_ids
                )
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))


def _wait_for_unbound_office_processes_exit(
    application: str,
    candidate_process_ids: frozenset[int],
    baseline: _OfficeProcessObservation,
    timeout_seconds: float = 30.0,
) -> bool | None:
    """Observe unbound candidates for natural exit without inferring ownership."""

    import time

    deadline = time.monotonic() + max(float(timeout_seconds), 0.0)
    while True:
        observed = _office_process_ids(application)
        if observed is None:
            return None
        candidate_states = {
            process_id: observed.identity_state(process_id)
            for process_id in candidate_process_ids
        }
        if any(
            state in {"nonmatching", "unresolved"}
            for state in candidate_states.values()
        ):
            return None
        unexpected_matching = (
            observed.matching_process_ids
            - baseline.matching_process_ids
            - candidate_process_ids
        )
        if unexpected_matching:
            return None
        if all(state == "absent" for state in candidate_states.values()):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))


def _wait_for_office_process_exit(
    application: str,
    process_id: int,
    timeout_seconds: float = 30.0,
) -> bool | None:
    import time

    deadline = time.monotonic() + max(float(timeout_seconds), 0.0)
    while True:
        observed = _office_process_ids(
            application,
            priority_process_id=process_id,
        )
        if observed is None:
            return None
        state = observed.identity_state(process_id)
        if state == "absent":
            return True
        if state == "nonmatching":
            return None
        if state not in {"matching", "unresolved"}:
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))


def _window_process_id(window_handle: int) -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        handle = wintypes.HWND(window_handle)
        if not user32.IsWindow(handle):
            return None
        owner = wintypes.DWORD()
        if not user32.GetWindowThreadProcessId(handle, ctypes.byref(owner)):
            return None
        process_id = int(owner.value)
        return process_id if process_id > 0 else None
    except Exception:
        return None


def _has_visible_window(process_id: int) -> bool | None:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        visible = False
        observation_failed = False

        @callback_type
        def inspect(window: int, _parameter: int) -> bool:
            nonlocal observation_failed, visible
            owner = wintypes.DWORD()
            if not user32.GetWindowThreadProcessId(window, ctypes.byref(owner)):
                observation_failed = True
                return False
            if int(owner.value) == process_id and user32.IsWindowVisible(window):
                visible = True
                return False
            return True

        ctypes.set_last_error(0)
        enumerated = bool(user32.EnumWindows(inspect, 0))
        if visible:
            return True
        if observation_failed:
            return None
        if enumerated:
            return False
        return None
    except Exception:
        return None


def _stream_metadata(prefix: str, payload: bytes) -> dict[str, Any]:
    bounded = payload[:4096]
    return {
        f"{prefix}_bytes": len(bounded),
        f"{prefix}_sha256": _payload_hash(bounded),
        f"{prefix}_truncated": len(payload) > len(bounded),
    }


def project_timeout_evidence(
    *,
    application: str,
    detection: dict[str, Any],
    termination: dict[str, Any],
    drain_status: str,
    stdout: bytes,
    stderr: bytes,
) -> dict[str, Any]:
    """Project a timeout using trusted identity and harness-owned cleanup facts."""

    cleanup_category = termination.get("cleanup_category")
    if cleanup_category not in _CLEANUP_CATEGORIES:
        cleanup_category = "cleanup-internal-error"
    return {
        **detection,
        **trusted_office_identity(application, detection),
        "outcome": "fail",
        "category": "timeout",
        "descendants_cleaned": termination.get("descendants_cleaned") is True,
        "cleanup_category": cleanup_category,
        "post_termination_drain": (
            drain_status if drain_status in {"complete", "error", "timeout"} else "error"
        ),
        **_stream_metadata("stdout", stdout),
        **_stream_metadata("stderr", stderr),
    }


def _terminate_tree(
    pid: int,
    *,
    target: _HeldWindowsProcess | None = None,
) -> dict[str, Any]:
    if target is not None:
        return _terminate_held_tree(pid, target)
    return _terminate_pid_tree(pid)


def _terminate_pid_tree(pid: int) -> dict[str, Any]:
    """Clean a harness-owned tree for which PID-based ownership is sufficient."""

    cleanup_category = "taskkill-complete"
    try:
        descendant_handles = _open_descendant_handles(pid)
    except Exception:
        descendant_handles = []
        cleanup_category = "descendant-enumeration-error"
    try:
        try:
            result = subprocess.run(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                shell=False,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            result = None
            cleanup_category = "taskkill-timeout"
        except (OSError, subprocess.SubprocessError):
            result = None
            cleanup_category = "taskkill-error"
        try:
            descendant_handles.extend(_open_descendant_handles(pid))
        except Exception:
            if cleanup_category == "taskkill-complete":
                cleanup_category = "descendant-enumeration-error"
        cleaned = (
            result is not None
            and result.returncode == 0
            and cleanup_category == "taskkill-complete"
        )
        if result is not None and result.returncode != 0:
            cleanup_category = "taskkill-nonzero"
        if not descendant_handles:
            return {
                "descendants_cleaned": cleaned,
                "cleanup_category": cleanup_category,
            }

        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            wait_object_0 = 0
            wait_timeout = 258
            for handle in descendant_handles:
                outcome = kernel32.WaitForSingleObject(handle, 250)
                if outcome == wait_timeout:
                    if not kernel32.TerminateProcess(handle, 1):
                        cleaned = False
                        continue
                    outcome = kernel32.WaitForSingleObject(handle, 2000)
                if outcome != wait_object_0:
                    cleaned = False
        except Exception:
            cleaned = False
            cleanup_category = "descendant-cleanup-error"
        if not cleaned and cleanup_category == "taskkill-complete":
            cleanup_category = "descendant-cleanup-incomplete"
        return {
            "descendants_cleaned": cleaned,
            "cleanup_category": cleanup_category,
        }
    finally:
        if descendant_handles:
            try:
                import ctypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                for handle in descendant_handles:
                    try:
                        kernel32.CloseHandle(handle)
                    except Exception:
                        pass
            except Exception:
                pass


def _terminate_held_tree(
    pid: int,
    target: _HeldWindowsProcess,
) -> dict[str, Any]:
    """Fail-closed cleanup for a fully bound Office process object tree."""

    descendants: list[_HeldWindowsProcess] = []
    target_terminated = False
    target_exited = False
    descendants_cleaned = False
    try:
        if target.process_id != pid or target.is_running() is not True:
            return _held_tree_result(False, False, False)
        first = _snapshot_processes()
        if first is None or not _snapshot_target_matches(first, target):
            return _held_tree_result(False, False, False)
        first_descendants = _descendant_process_ids(first, pid)
        if first_descendants is None:
            return _held_tree_result(False, False, False)
        for descendant_id in sorted(first_descendants):
            held = _open_held_office_process(descendant_id)
            if held is None:
                return _held_tree_result(False, False, False)
            descendants.append(held)
            expected_image = first[descendant_id][1]
            if (
                held.is_running() is not True
                or not expected_image
                or held.image_name.casefold() != expected_image.casefold()
            ):
                return _held_tree_result(False, False, False)

        second = _snapshot_processes()
        if second is None or not _snapshot_target_matches(second, target):
            return _held_tree_result(False, False, False)
        second_descendants = _descendant_process_ids(second, pid)
        if second_descendants != first_descendants:
            return _held_tree_result(False, False, False)
        if any(
            first[descendant_id] != second.get(descendant_id)
            for descendant_id in first_descendants
        ):
            return _held_tree_result(False, False, False)
        if target.is_running() is not True:
            return _held_tree_result(False, False, False)
        if any(held.is_running() is not True for held in descendants):
            return _held_tree_result(False, False, False)

        termination = target.terminate()
        if termination is None:
            return _held_tree_result(False, False, False)
        target_terminated = termination is True
        target_exited = target.wait(5_000) is True

        descendants_cleaned = True
        for held in reversed(descendants):
            running = held.is_running()
            if running is None:
                descendants_cleaned = False
                continue
            if running:
                terminated = held.terminate()
                if terminated is None:
                    descendants_cleaned = False
                    continue
            if held.wait(5_000) is not True:
                descendants_cleaned = False
        return _held_tree_result(
            target_terminated,
            target_exited,
            descendants_cleaned and target_exited,
        )
    except Exception:
        return _held_tree_result(
            target_terminated,
            target_exited,
            False,
        )
    finally:
        for held in descendants:
            held.close()


def _held_tree_result(
    target_terminated: bool,
    target_exited: bool,
    cleaned: bool,
) -> dict[str, Any]:
    return {
        "descendants_cleaned": cleaned,
        "cleanup_category": (
            "handle-tree-complete" if cleaned else "handle-tree-incomplete"
        ),
        "target_terminated": target_terminated,
        "target_exited": target_exited,
    }


def _snapshot_target_matches(
    processes: dict[int, tuple[int, str]],
    target: _HeldWindowsProcess,
) -> bool:
    target_record = processes.get(target.process_id)
    return (
        target_record is not None
        and bool(target_record[1])
        and target_record[1].casefold() == target.image_name.casefold()
    )


def _descendant_process_ids(
    processes: dict[int, tuple[int, str]],
    pid: int,
) -> set[int] | None:
    descendants: set[int] = set()
    frontier = {pid}
    while frontier:
        children = {
            child
            for child, (parent, _image) in processes.items()
            if (
                parent in frontier
                and child != pid
                and child not in descendants
            )
        }
        if children & frontier:
            return None
        descendants.update(children)
        frontier = children
    return descendants


def _snapshot_processes() -> dict[int, tuple[int, str]] | None:
    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return None
    processes: dict[int, tuple[int, str]] = {}
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        ctypes.set_last_error(0)
        present = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        if not present:
            error = ctypes.get_last_error()
            return {} if error in {0, 18} else None
        while present:
            processes[int(entry.th32ProcessID)] = (
                int(entry.th32ParentProcessID),
                str(entry.szExeFile),
            )
            ctypes.set_last_error(0)
            present = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() not in {0, 18}:
            return None
    finally:
        kernel32.CloseHandle(snapshot)
    return processes


def _open_descendant_handles(pid: int) -> list[int]:
    """Pin descendant process objects before ``taskkill`` can orphan them."""

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    snapshot = _snapshot_processes()
    if snapshot is None:
        raise OSError("process snapshot unavailable")
    parents = {
        process_id: parent_id
        for process_id, (parent_id, _image) in snapshot.items()
    }

    descendants: set[int] = set()
    frontier = {pid}
    while frontier:
        children = {
            child
            for child, parent in parents.items()
            if parent in frontier and child not in descendants
        }
        descendants.update(children)
        frontier = children

    access = 0x0001 | 0x00100000
    handles: list[int] = []
    for descendant in sorted(descendants):
        handle = kernel32.OpenProcess(access, False, descendant)
        if handle:
            handles.append(handle)
    return handles


def _payload_hash(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()
