"""Safe, bounded Microsoft Office detection and COM open probes."""

from __future__ import annotations

import base64
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
_POWERSHELL = {
    "word": r"""
$app = New-Object -ComObject Word.Application
$version = [string]$app.Version
@{ event = 'identity'; application = 'word'; version = $version } | ConvertTo-Json -Compress
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
@{ event = 'identity'; application = 'excel'; version = $version } | ConvertTo-Json -Compress
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
@{ event = 'identity'; application = 'powerpoint'; version = $version } | ConvertTo-Json -Compress
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


def open_with_office(application: str, artifact: Path, timeout_seconds: float) -> dict[str, Any]:
    """Open read-only in an isolated PowerShell child and never save."""

    if application not in _POWERSHELL:
        raise ValueError(f"Unknown Office application: {application}")
    if os.name != "nt":
        return {"outcome": "unavailable", "category": "not-windows"}
    identity = detect_office(application)
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
    except subprocess.TimeoutExpired:
        cleaned = _terminate_tree(process.pid)
        stdout, stderr = process.communicate(timeout=5)
        payload = _parse_probe_output(stdout)
        return {
            **identity,
            **payload,
            "outcome": "fail",
            "category": "timeout",
            "descendants_cleaned": cleaned,
            "stdout_bytes": len(stdout[:4096]),
            "stderr_bytes": len(stderr[:4096]),
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
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
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


def _terminate_tree(pid: int) -> bool:
    descendant_handles = _open_descendant_handles(pid)
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
        descendant_handles.extend(_open_descendant_handles(pid))
        cleaned = result.returncode == 0
        if not descendant_handles:
            return cleaned

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
        return cleaned
    finally:
        if descendant_handles:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            for handle in descendant_handles:
                kernel32.CloseHandle(handle)


def _open_descendant_handles(pid: int) -> list[int]:
    """Pin descendant process objects before ``taskkill`` can orphan them."""

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
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return []
    parents: dict[int, int] = {}
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        present = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while present:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            present = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

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
