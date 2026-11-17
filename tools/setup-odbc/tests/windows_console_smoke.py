"""Isolated hidden-console test driver, not part of the shipped application."""

import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    exe, mode, argument = sys.argv[1:]
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("PYTHON") and key.upper() not in
           {"VIRTUAL_ENV", "CI", "GITHUB_ACTIONS", "TF_BUILD", "PYTEST_CURRENT_TEST"}}
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    if mode == "ci":
        env["CI"] = "true"
    command = [exe, argument]
    if mode == "terminal":
        shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        command = [str(shell), "-NoProfile", "-Command", "& '" + exe.replace("'", "''") + "' " + argument + "; exit $LASTEXITCODE"]
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    child = subprocess.Popen(command, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.FreeConsole()
    kernel.AttachConsole.argtypes = [w.DWORD]
    kernel.AttachConsole.restype = w.BOOL
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handles = []
    paused = False
    try:
        if mode != "owned":
            code = child.wait(timeout=25)  # a pause would make this fail
        else:
            # Leave the child console alone while its ownership detector runs.
            # Attaching this observer earlier would make it caller-owned.
            try:
                child.wait(timeout=10)
                raise RuntimeError("Explorer-owned console closed before Enter")
            except subprocess.TimeoutExpired:
                pass
            if not kernel.AttachConsole(child.pid):
                raise c.WinError(c.get_last_error())
            for name in ("CONOUT$", "CONIN$"):
                handle = kernel.CreateFileW(name, 0xC0000000, 3, None, 3, 0, None)
                if handle == c.c_void_p(-1).value:
                    raise c.WinError(c.get_last_error())
                handles.append(handle)

            class Coord(c.Structure):
                _fields_ = [("x", w.SHORT), ("y", w.SHORT)]
            class Character(c.Union):
                _fields_ = [("UnicodeChar", w.WCHAR), ("AsciiChar", c.c_char)]
            class Key(c.Structure):
                _fields_ = [("down", w.BOOL), ("repeat", w.WORD), ("virtual", w.WORD),
                            ("scan", w.WORD), ("character", Character), ("control", w.DWORD)]
            class Event(c.Union):
                _fields_ = [("key", Key), ("padding", c.c_byte * 16)]
            class InputRecord(c.Structure):
                _fields_ = [("type", w.WORD), ("event", Event)]
            kernel.ReadConsoleOutputCharacterW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, Coord, c.POINTER(w.DWORD)]
            kernel.WriteConsoleInputW.argtypes = [w.HANDLE, c.POINTER(InputRecord), w.DWORD, c.POINTER(w.DWORD)]
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                screen, count = c.create_unicode_buffer(32768), w.DWORD()
                if not kernel.ReadConsoleOutputCharacterW(handles[0], screen, 32767, Coord(0, 0), c.byref(count)):
                    raise c.WinError(c.get_last_error())
                if "Press Enter to close this window..." in screen.value:
                    paused = True
                    break
                time.sleep(0.02)
            if not paused or child.poll() is not None:
                raise RuntimeError("Expected a live console waiting for Enter")
            record = InputRecord(1, Event(key=Key(True, 1, 13, 0, Character(UnicodeChar="\r"), 0)))
            count = w.DWORD()
            if not kernel.WriteConsoleInputW(handles[1], c.byref(record), 1, c.byref(count)):
                raise c.WinError(c.get_last_error())
            code = child.wait(timeout=10)
        print(json.dumps({"returncode": code, "paused": paused}))
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)
        kernel.FreeConsole()
        if child.poll() is None:
            # Kill only this test's process tree, including the onefile child.
            subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, timeout=10)
            child.wait(timeout=10)


if __name__ == "__main__":
    main()
