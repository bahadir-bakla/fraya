"""Windows MCP launcher with DPAPI credentials and no intermediate shell pipes.

DPAPI API: https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata
Encrypted files are local to the current Windows user and excluded from Git.
Other machines can inject the two FREYA_* keys through process environment.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "skill-creator-skill-lift" / "integrations" / "freya-mcp"


def unprotect(path: Path) -> str:
    encrypted = bytes.fromhex(path.read_text(encoding="ascii").strip())

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(encrypted)).from_buffer_copy(encrypted)
    source, destination = Blob(len(encrypted), buffer), Blob()
    crypto = ctypes.WinDLL("crypt32", use_last_error=True)
    crypto.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypto.CryptUnprotectData.restype = wintypes.BOOL
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not crypto.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
        raise RuntimeError("Local credential decryption failed for this Windows user")
    try:
        return ctypes.string_at(destination.data, destination.size).decode("utf-16-le")
    finally:
        ctypes.memset(destination.data, 0, destination.size)
        kernel.LocalFree(destination.data)


def inject_credentials() -> None:
    for filename, name in [("freya-key.dpapi", "FREYA_API_KEY"), ("freya-bank-key.dpapi", "FREYA_BANK_TEAM_KEY")]:
        path = ROOT / ".local-secrets" / filename
        if not os.environ.get(name) and path.is_file():
            if os.name != "nt":
                raise RuntimeError("Inject credentials through environment on non-Windows systems")
            os.environ[name] = unprotect(path)


def main() -> int:
    try:
        inject_credentials()
    except Exception:
        print("Freya credential setup failed; details withheld.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(INTEGRATION))
    from freya_mcp.server import main as server_main
    sys.argv[1:1] = ["--workspace", str(ROOT)]
    return server_main()


if __name__ == "__main__":
    raise SystemExit(main())
