"""Native console smoke driver; only synthetic loopback data and temporary files.

The HTTP gate proves console ownership was checked before the observer attaches.
No timing assumption about onefile extraction is needed.
"""

import ctypes
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4


def main():
    exe, mode, outcome = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    reached, release = threading.Event(), threading.Event()
    token = uuid4().hex
    root = exe.parent
    (root / "symbols").mkdir()
    (root / "footprints").mkdir()
    (root / "symbols" / "Example.SchLib").write_bytes(b"synthetic")
    (root / "footprints" / "Example.PcbLib").write_bytes(b"synthetic")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            reached.set()
            release.wait(30)
            if outcome == "error" or self.headers.get("Authorization") != "Token " + token:
                self.send_response(401)
                self.end_headers()
                return
            parameters = [
                {"pk": 1, "model_id": 20, "template": 1, "data": "Example.SchLib:Resistor",
                 "template_detail": {"pk": 1, "name": "Altium Symbol", "units": ""}},
                {"pk": 2, "model_id": 20, "template": 2, "data": "Example.PcbLib:R0603",
                 "template_detail": {"pk": 2, "name": "Altium Footprint", "units": ""}},
            ]
            records = ([{"pk": 1, "name": "Resistors", "parent": None}]
                       if self.path.startswith("/api/part/category/") else
                       [{"pk": 20, "IPN": "SYNTHETIC-20", "category": 1, "parameters": parameters}])
            body = json.dumps(records).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = root / "config.toml"
    config.write_text(f'[inventree]\nbase_url="http://127.0.0.1:{server.server_port}"\n'
                      'auth="token"\nretries=0\n[scope]\nroot_category_path=["Resistors"]\n'
                      '[sync]\noutput="components.sqlite"\ndblib="Components.DbLib"\n'
                      '[libraries]\nsymbols="symbols"\nfootprints="footprints"\n', encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")
           and k.upper() not in {"CI", "GITHUB_ACTIONS", "TF_BUILD", "VIRTUAL_ENV"}}
    env["INVENTREE_API_TOKEN"] = token
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    if mode == "ci":
        env["GITHUB_ACTIONS"] = "true"

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.FreeConsole()
    kernel.AttachConsole.argtypes = [wintypes.DWORD]
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    class Coord(ctypes.Structure):
        _fields_ = [("x", wintypes.SHORT), ("y", wintypes.SHORT)]
    kernel.ReadConsoleOutputCharacterW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, Coord, ctypes.POINTER(wintypes.DWORD)]
    class Character(ctypes.Union):
        _fields_ = [("UnicodeChar", wintypes.WCHAR), ("AsciiChar", ctypes.c_char)]
    class Key(ctypes.Structure):
        _fields_ = [("down", wintypes.BOOL), ("repeat", wintypes.WORD), ("virtual", wintypes.WORD), ("scan", wintypes.WORD), ("character", Character), ("control", wintypes.DWORD)]
    class Event(ctypes.Union):
        _fields_ = [("key", Key), ("padding", ctypes.c_byte * 16)]
    class InputRecord(ctypes.Structure):
        _fields_ = [("type", wintypes.WORD), ("event", Event)]
    kernel.WriteConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(InputRecord), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    # In terminal mode PowerShell remains attached while its child runs.
    command = [str(exe)]
    if mode == "terminal":
        shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        command = [str(shell), "-NoProfile", "-Command", "& '" + str(exe).replace("'", "''") + "'; exit $LASTEXITCODE"]
    process = subprocess.Popen(command, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)
    handles = []
    screen = ""
    paused = False
    try:
        if not reached.wait(25):
            raise RuntimeError(f"Executable did not reach loopback API; status={process.poll()}")
        if not kernel.AttachConsole(process.pid):
            raise ctypes.WinError(ctypes.get_last_error())
        for name in ("CONOUT$", "CONIN$"):
            handle = kernel.CreateFileW(name, 0xC0000000, 3, None, 3, 0, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
        release.set()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            buffer, count = ctypes.create_unicode_buffer(32768), wintypes.DWORD()
            if kernel.ReadConsoleOutputCharacterW(handles[0], buffer, 32767, Coord(0, 0), ctypes.byref(count)):
                screen = buffer.value
            if "Press Enter to close this window..." in screen:
                paused = True
                if process.poll() is not None:
                    raise RuntimeError("Console prompt did not wait")
                record = InputRecord(1, Event(key=Key(True, 1, 13, 0, Character(UnicodeChar="\r"), 0)))
                if not kernel.WriteConsoleInputW(handles[1], ctypes.byref(record), 1, ctypes.byref(count)):
                    raise ctypes.WinError(ctypes.get_last_error())
                break
            if process.poll() is not None:
                break
            time.sleep(0.02)
        code = process.wait(timeout=10)
        report = {"returncode": code, "paused": paused, "published": (root / "components.sqlite").is_file(),
                  "success": "Synchronization successful" in screen, "api_error": "API error" in screen,
                  "secret_leaked": token in screen, "screen": screen.strip() if token not in screen else "<redacted>"}
    finally:
        release.set()
        for handle in handles:
            kernel.CloseHandle(handle)
        kernel.FreeConsole()
        if process.poll() is None:
            process.kill()
            process.wait()
        server.shutdown()
        server.server_close()
    print(json.dumps(report))


if __name__ == "__main__":
    main()
