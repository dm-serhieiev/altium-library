"""Pause a frozen Windows application's own console, never a caller's terminal."""

import os
from pathlib import Path
import sys

from .cli import main


def _owns_windows_console() -> bool:
    # PyInstaller onefile has both a bootloader parent and an application child.
    # A terminal/shell attached to this console makes it caller-owned.
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetConsoleProcessList.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    kernel.GetConsoleProcessList.restype = wintypes.DWORD
    processes = (wintypes.DWORD * 3)()
    count = kernel.GetConsoleProcessList(processes, len(processes))
    if count == 1:
        return processes[0] == os.getpid()
    if count != 2 or set(processes[:count]) != {os.getpid(), os.getppid()}:
        return False

    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, os.getppid())  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        size = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            return False
        return Path(image.value).resolve() == Path(sys.executable).resolve()
    finally:
        kernel.CloseHandle(handle)


def should_pause() -> bool:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    if any(os.environ.get(name, "").casefold() not in {"", "0", "false"}
           for name in ("CI", "GITHUB_ACTIONS", "TF_BUILD", "PYTEST_CURRENT_TEST")):
        return False
    try:
        if not all(stream is not None and stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
            return False
        return _owns_windows_console()
    except (OSError, ValueError, AttributeError):
        # An uncertain console must not block automation.
        return False


def run_cli(argv: list[str] | None = None) -> int:
    # Console Unicode uses the Windows console API; redirected diagnostics use a
    # predictable encoding even when paths contain characters outside the ACP.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    pause = should_pause()
    try:
        try:
            return main(argv)
        except SystemExit as exc:
            # argparse help and usage errors must pass through the same finalizer.
            return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    finally:
        if pause:
            try:
                input("Press Enter to close this window...")
            except (EOFError, OSError, KeyboardInterrupt):
                pass  # Preserve the command's exit status.
