"""Windows-only executable/getpass driver, invoked by test_packaging.py."""

import base64
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
    exe, config = map(Path, sys.argv[1:])
    username, password = "packaging-user", uuid4().hex
    authorization = "Basic " + base64.b64encode(f"{username}:{password}".encode("ascii")).decode("ascii")
    authenticated = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Authorization") != authorization:
                self.send_response(401)
                self.end_headers()
                return
            authenticated.append(self.path)
            records = ([{"pk": 1, "name": "Electronic Components", "parent": None}]
                       if self.path.startswith("/api/part/category/") else
                       [{"pk": 20, "IPN": "EXAMPLE-20", "category": 1, "parameters": []}])
            body = json.dumps(records).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    example = config.with_name("config.example.toml").read_text(encoding="utf-8")
    config.write_text(example.replace("https://inventree.example.com", f"http://127.0.0.1:{server.server_port}"), encoding="utf-8")
    before = config.read_bytes()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON") and k.upper() not in {"VIRTUAL_ENV", "INVENTREE_API_TOKEN"}}
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    process = subprocess.Popen([str(exe), "inspect"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.FreeConsole()  # The isolated driver may inherit a hidden console.
    kernel.AttachConsole.argtypes = [wintypes.DWORD]
    kernel.AttachConsole.restype = wintypes.BOOL
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    class Character(ctypes.Union):
        _fields_ = [("UnicodeChar", wintypes.WCHAR), ("AsciiChar", ctypes.c_char)]

    class Key(ctypes.Structure):
        _fields_ = [("down", wintypes.BOOL), ("repeat", wintypes.WORD), ("virtual", wintypes.WORD), ("scan", wintypes.WORD), ("character", Character), ("control", wintypes.DWORD)]

    class Event(ctypes.Union):
        _fields_ = [("key", Key), ("padding", ctypes.c_byte * 16)]

    class InputRecord(ctypes.Structure):
        _fields_ = [("type", wintypes.WORD), ("event", Event)]

    kernel.WriteConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(InputRecord), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.WriteConsoleInputW.restype = wintypes.BOOL
    attached = False
    handle = None
    try:
        for _ in range(100):
            if kernel.AttachConsole(process.pid):
                attached = True
                break
            time.sleep(0.02)
        if not attached:
            raise RuntimeError(f"Cannot attach to the executable's smoke-test console (Windows error {ctypes.get_last_error()}, child status {process.poll()})")
        handle = kernel.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            raise RuntimeError("Cannot open the executable's console input")
        records = (InputRecord * (len(password) + 1))()
        for i, char in enumerate(password + "\r"):
            records[i].type = 1
            records[i].event.key = Key(True, 1, 13 if char == "\r" else ord(char.upper()), 0, Character(UnicodeChar=char), 0)
        written = wintypes.DWORD()
        if not kernel.WriteConsoleInputW(handle, records, len(records), ctypes.byref(written)) or written.value != len(records):
            raise RuntimeError("Cannot deliver secure console input")
        process.stdin.write(username + "\n")
        process.stdin.close()
        process.stdin = None
        stdout, stderr = process.communicate(timeout=25)
        print(json.dumps({"returncode": process.returncode, "stdout": stdout, "stderr": stderr,
                          "authenticated_requests": len(authenticated),
                          "password_leaked": password in stdout + stderr or authorization in stdout + stderr,
                          "credentials_persisted": config.read_bytes() != before or password.encode() in config.read_bytes()}))
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
        if attached:
            kernel.FreeConsole()
        if process.poll() is None:
            process.kill()
            process.wait()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
