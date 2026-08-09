"""Bounded binary pipe collectors used by the external-process runner."""

import tempfile
import threading
from typing import BinaryIO


class BoundedPipeCollector:
    def __init__(self, stream: BinaryIO, byte_limit: int) -> None:
        self._stream = stream
        self._byte_limit = byte_limit
        self._spool = tempfile.SpooledTemporaryFile(max_size=min(byte_limit, 65_536))
        self._thread = threading.Thread(target=self._collect, daemon=True)
        self.done = threading.Event()
        self.overflow = threading.Event()
        self.total_bytes = 0

    def start(self) -> None:
        self._thread.start()

    def wait(self, timeout: float) -> bool:
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def bytes(self) -> bytes:
        self._spool.seek(0)
        return self._spool.read()

    def close(self) -> None:
        self._spool.close()

    def abort(self) -> None:
        try:
            self._stream.close()
        except (OSError, ValueError):
            pass

    def _collect(self) -> None:
        try:
            while True:
                chunk = self._stream.read(65_536)
                if not chunk:
                    break
                self.total_bytes += len(chunk)
                remaining = max(self._byte_limit - self._spool.tell(), 0)
                if remaining:
                    self._spool.write(chunk[:remaining])
                if self.total_bytes > self._byte_limit:
                    self.overflow.set()
                    break
        except (OSError, ValueError):
            pass
        finally:
            try:
                self._stream.close()
            except (OSError, ValueError):
                pass
            self.done.set()
