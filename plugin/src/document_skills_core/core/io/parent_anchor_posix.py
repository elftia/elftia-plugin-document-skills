"""POSIX native operations used by destination-parent anchors."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path


def linux_rename_no_replace(
    descriptor: int,
    source: str,
    destination: str,
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = library.renameat2
    except AttributeError as error:
        raise OSError("renameat2 is unavailable") from error
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        descriptor,
        os.fsencode(source),
        descriptor,
        os.fsencode(destination),
        1,
    )
    if result != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), destination)


def darwin_rename_no_replace(
    descriptor: int,
    source: str,
    destination: str,
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    try:
        renameatx_np = library.renameatx_np
    except AttributeError as error:
        raise OSError("renameatx_np is unavailable") from error
    renameatx_np.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameatx_np.restype = ctypes.c_int
    result = renameatx_np(
        descriptor,
        os.fsencode(source),
        descriptor,
        os.fsencode(destination),
        4,
    )
    if result != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), destination)


def darwin_descriptor_path(descriptor: int) -> Path:
    buffer = ctypes.create_string_buffer(4096)
    library = ctypes.CDLL(None, use_errno=True)
    result = library.fcntl(descriptor, 50, buffer)
    if result != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    return Path(os.fsdecode(buffer.value)).resolve(strict=False)
