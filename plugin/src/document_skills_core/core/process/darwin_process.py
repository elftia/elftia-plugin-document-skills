"""Binary-pipe child interface used by the existing bounded process runner."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from typing import BinaryIO


class DarwinProcess:
    def __init__(
        self,
        command: list[str],
        stdin: BinaryIO,
        stdout: BinaryIO,
        stderr: BinaryIO,
    ) -> None:
        self.args = command
        self.pid = 0
        self.returncode: int | None = None
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self._wait_lock = threading.RLock()

    def poll(self) -> int | None:
        with self._wait_lock:
            if self.returncode is None:
                pid, status = os.waitpid(self.pid, os.WNOHANG)
                if pid == self.pid:
                    self.returncode = os.waitstatus_to_exitcode(status)
            return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._wait_lock:
                if self.returncode is not None:
                    return self.returncode
                result = self.poll()
                if result is not None:
                    return result
            if deadline is None:
                time.sleep(0.01)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(min(remaining, 0.01))

    def send_signal(self, sig: int) -> None:
        with self._wait_lock:
            if self.poll() is None:
                try:
                    os.kill(self.pid, sig)
                except ProcessLookupError:
                    # The child may exit between waitpid(WNOHANG) and kill.
                    # wait() must still reap it and collect its exit status.
                    pass

    def kill(self) -> None:
        self.send_signal(signal.SIGKILL)

    def terminate(self) -> None:
        self.send_signal(signal.SIGTERM)
