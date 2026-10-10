"""Private WinFsp volume ACL for the invoking user and SYSTEM only.

Module provenance: original Elftia-authored implementation.
"""

import ctypes as c

from ._quota_winfsp_abi import PTR, U32


def user_security_descriptor() -> bytes:
    kernel = c.WinDLL("kernel32.dll", winmode=0x800, use_last_error=True)
    advapi = c.WinDLL("advapi32.dll", winmode=0x800, use_last_error=True)
    kernel.GetCurrentProcess.argtypes, kernel.GetCurrentProcess.restype = [], PTR
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [PTR], c.c_int32
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [PTR], PTR
    advapi.OpenProcessToken.argtypes = [PTR, U32, c.POINTER(PTR)]
    advapi.OpenProcessToken.restype = c.c_int32
    advapi.GetTokenInformation.argtypes = [PTR, U32, PTR, U32, c.POINTER(U32)]
    advapi.GetTokenInformation.restype = c.c_int32
    advapi.ConvertSidToStringSidW.argtypes = [PTR, c.POINTER(PTR)]
    advapi.ConvertSidToStringSidW.restype = c.c_int32
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        c.c_wchar_p, U32, c.POINTER(PTR), c.POINTER(U32),
    ]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = c.c_int32
    token = PTR()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, c.byref(token)):
        raise c.WinError(c.get_last_error())
    try:
        needed = U32()
        advapi.GetTokenInformation(token, 1, None, 0, c.byref(needed))
        if not 0 < needed.value <= 65536:
            raise OSError("Invalid Windows token-user size.")
        buffer = c.create_string_buffer(needed.value)
        if not advapi.GetTokenInformation(token, 1, buffer, len(buffer), c.byref(needed)):
            raise c.WinError(c.get_last_error())
        sid = c.cast(buffer, c.POINTER(PTR))[0]
        text = PTR()
        if not advapi.ConvertSidToStringSidW(sid, c.byref(text)):
            raise c.WinError(c.get_last_error())
        try:
            user_sid = c.wstring_at(text)
        finally:
            kernel.LocalFree(text)
        sddl = f"O:{user_sid}G:SYD:P(A;;FA;;;{user_sid})(A;;FA;;;SY)"
        descriptor, size = PTR(), U32()
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, c.byref(descriptor), c.byref(size),
        ):
            raise c.WinError(c.get_last_error())
        try:
            if not 0 < size.value <= 65536:
                raise OSError("Invalid private Windows security descriptor size.")
            return c.string_at(descriptor, size.value)
        finally:
            kernel.LocalFree(descriptor)
    finally:
        kernel.CloseHandle(token)
