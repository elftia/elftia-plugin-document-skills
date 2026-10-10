"""Cross-platform process-tree ownership and bounded termination."""

import ctypes
from ctypes import wintypes
import os
import signal
import subprocess
import sys
import time


class ProcessTree:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process
        self._job: int | None = self._create_windows_job() if os.name == "nt" else None

    def terminate(self) -> None:
        if os.name == "nt":
            if self._job is not None:
                terminate_job = ctypes.windll.kernel32.TerminateJobObject
                terminate_job.argtypes = [wintypes.HANDLE, wintypes.UINT]
                terminate_job.restype = wintypes.BOOL
                terminate_job(wintypes.HANDLE(self._job), 1)
            else:
                self._taskkill_fallback()
            try:
                self.process.kill()
            except OSError:
                pass
            return
        self._terminate_posix_group()

    def _terminate_posix_group(self) -> None:
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Darwin can return EPERM while an exiting group is being removed,
            # even after waitpid has reaped its leader. Retry within a fixed
            # budget, reaping on each attempt; persistent denial still fails.
            if sys.platform != "darwin":
                raise
            for attempt in range(20):
                self.process.poll()
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    return
                except ProcessLookupError:
                    return
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.01)

    def close(self) -> None:
        if self._job is not None:
            close_handle = ctypes.windll.kernel32.CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL
            close_handle(wintypes.HANDLE(self._job))
            self._job = None

    def _create_windows_job(self) -> int | None:
        kernel32 = ctypes.windll.kernel32
        create_job = kernel32.CreateJobObjectW
        create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        create_job.restype = wintypes.HANDLE
        job = create_job(None, None)
        if not job:
            return None
        information = _JobObjectExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        set_information = kernel32.SetInformationJobObject
        set_information.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        set_information.restype = wintypes.BOOL
        configured = set_information(
            job,
            9,
            ctypes.byref(information),
            ctypes.sizeof(information),
        )
        assign_process = kernel32.AssignProcessToJobObject
        assign_process.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        assign_process.restype = wintypes.BOOL
        assigned = configured and assign_process(
            job, wintypes.HANDLE(int(self.process._handle))
        )
        if assigned:
            return int(job)
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        close_handle(job)
        return None

    def _taskkill_fallback(self) -> None:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                shell=False,
                timeout=2.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]
