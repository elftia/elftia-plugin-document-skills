"""Spawn a native Darwin image suspended; authorize it before SIGCONT."""

from __future__ import annotations

import ctypes
import os
import signal
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

from .darwin_abi import DarwinAPI, SPAWN_FLAGS
from .darwin_image import verify_suspended_image
from .darwin_process import DarwinProcess

if TYPE_CHECKING:
    from .executable import ExecutableLaunchLease


def _check(result: int) -> None:
    if result != 0:
        raise OSError(result, "Darwin native process setup failed")


def _encoded(value: str | Path) -> bytes:
    result = os.fsencode(value)
    if b"\0" in result:
        raise ValueError("Process argument contains a NUL byte")
    return result


def _launch_environment(launch: ExecutableLaunchLease, env: dict[str, str]) -> dict[str, str]:
    environment = dict(env)
    if launch.identity.resolved_path == Path(sys.executable).resolve(strict=True):
        # Framework Python uses its kernel executable path instead of argv[0].
        # Preserve the authorized venv alias while still spawning and checking
        # the canonical native image. Never inherit a caller-selected override.
        environment["PYTHONEXECUTABLE"] = str(launch.launch_path)
    return environment


def _pipe(api: DarwinAPI, owned: set[int]) -> tuple[int, int]:
    descriptors = list(os.pipe())
    owned.update(descriptors)
    for index, descriptor in enumerate(descriptors):
        if descriptor < 3:
            duplicate = api.libc.fcntl(descriptor, 67, 3)  # F_DUPFD_CLOEXEC
            if duplicate < 0:
                raise OSError(ctypes.get_errno(), "Pipe descriptor duplication failed")
            owned.add(duplicate)
            os.close(descriptor)
            owned.remove(descriptor)
            descriptors[index] = duplicate
    return descriptors[0], descriptors[1]


def _attributes(api: DarwinAPI, resources: ExitStack) -> ctypes.c_void_p:
    attributes = ctypes.c_void_p()
    _check(api.libc.posix_spawnattr_init(ctypes.byref(attributes)))
    resources.callback(api.libc.posix_spawnattr_destroy, ctypes.byref(attributes))
    _check(api.libc.posix_spawnattr_setflags(ctypes.byref(attributes), SPAWN_FLAGS))
    mask = ctypes.c_uint32()
    defaults = ctypes.c_uint32()
    _check(api.libc.sigemptyset(ctypes.byref(mask)))
    _check(api.libc.sigemptyset(ctypes.byref(defaults)))
    for sig in (signal.SIGPIPE, signal.SIGXFSZ):
        _check(api.libc.sigaddset(ctypes.byref(defaults), sig))
    _check(api.libc.posix_spawnattr_setsigmask(ctypes.byref(attributes), ctypes.byref(mask)))
    _check(api.libc.posix_spawnattr_setsigdefault(
        ctypes.byref(attributes), ctypes.byref(defaults)
    ))
    return attributes


def spawn_authorized_process(
    command: list[str],
    *,
    launch: ExecutableLaunchLease,
    cwd: Path,
    env: dict[str, str],
    pass_fds: tuple[int, ...] = (),
    close_fds: bool = True,
) -> DarwinProcess:
    if close_fds is not True:
        raise ValueError("Darwin launches must close unrelated descriptors")
    if launch._fd is None:
        raise OSError(9, "Darwin executable lease is not held")  # Darwin EBADF
    try:
        api = DarwinAPI()
    except (AttributeError, OSError) as error:
        raise OSError(78, "Darwin native spawn API is unavailable") from error  # ENOSYS
    owned: set[int] = set()
    process: DarwinProcess | None = None
    with ExitStack() as streams, ExitStack() as resources:
        try:
            input_read, input_write = _pipe(api, owned)
            output_read, output_write = _pipe(api, owned)
            error_read, error_write = _pipe(api, owned)
            stdin = streams.enter_context(os.fdopen(input_write, "wb"))
            owned.remove(input_write)
            stdout = streams.enter_context(os.fdopen(output_read, "rb"))
            owned.remove(output_read)
            stderr = streams.enter_context(os.fdopen(error_read, "rb"))
            owned.remove(error_read)
            process = DarwinProcess(command, stdin, stdout, stderr)
            actions = ctypes.c_void_p()
            _check(api.libc.posix_spawn_file_actions_init(ctypes.byref(actions)))
            resources.callback(api.libc.posix_spawn_file_actions_destroy, ctypes.byref(actions))
            standard_streams = ((input_read, 0), (output_write, 1), (error_write, 2))
            for descriptor, standard in standard_streams:
                _check(api.libc.posix_spawn_file_actions_adddup2(
                    ctypes.byref(actions), descriptor, standard
                ))
            pipe_fds = (
                input_read, input_write, output_read, output_write, error_read, error_write
            )
            for descriptor in pipe_fds:
                _check(api.libc.posix_spawn_file_actions_addclose(
                    ctypes.byref(actions), descriptor
                ))
            for descriptor in pass_fds:
                _check(api.libc.posix_spawn_file_actions_addinherit_np(
                    ctypes.byref(actions), descriptor
                ))
            _check(api.libc.posix_spawn_file_actions_addchdir_np(
                ctypes.byref(actions), _encoded(cwd)
            ))
            attributes = _attributes(api, resources)
            arguments = (ctypes.c_char_p * (len(command) + 1))(*map(_encoded, command), None)
            launch_env = _launch_environment(launch, env)
            environment = (ctypes.c_char_p * (len(launch_env) + 1))(
                *[_encoded(f"{key}={value}") for key, value in launch_env.items()], None
            )
            pid = ctypes.c_int()
            _check(api.libc.posix_spawn(
                ctypes.byref(pid),
                _encoded(launch.popen_executable),
                ctypes.byref(actions),
                ctypes.byref(attributes),
                arguments,
                environment,
            ))
            process.pid = pid.value
            verify_suspended_image(api, process.pid, launch.identity, launch._fd)
            os.kill(process.pid, signal.SIGCONT)
            streams.pop_all()  # Ownership transfers to the bounded process runner.
            return process
        except BaseException:
            if process is not None and process.pid > 0:
                process.kill()
                process.wait(timeout=2.0)
            raise
        finally:
            for descriptor in owned:
                os.close(descriptor)
