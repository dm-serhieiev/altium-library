"""Exercise the actual PowerShell orchestration with a tiny fake build tool.

These fault-injection tests do not claim to compile Python; build.ps1 separately
runs real PyInstaller and test_packaging against its candidate before publishing.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture(scope="module")
def fake_python(tmp_path_factory):
    if sys.platform != "win32":
        pytest.skip("Windows PowerShell build orchestration")
    folder = tmp_path_factory.mktemp("fake-build-tool")
    source = folder / "Fake.cs"
    source.write_text(r'''
using System;
using System.IO;
using System.Reflection;
public class Fake {
    public static int Main(string[] args) {
        string phase;
        if (args[0] == "-c") phase = args[1].Contains("os.replace") ? "publish" : "version";
        else if (args[1] == "pytest") phase = Array.IndexOf(args, "--setup-executable") >= 0 ? "smoke" : "tests";
        else phase = args[1];
        File.AppendAllText(Environment.GetEnvironmentVariable("BUILD_TEST_LOG"), phase + "\n" + String.Join("|", args) + "\n");
        if (phase == Environment.GetEnvironmentVariable("BUILD_TEST_FAIL")) return 7;
        if (phase == "venv") {
            string target = Path.Combine(args[2], "Scripts", "python.exe");
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            File.Copy(Assembly.GetExecutingAssembly().Location, target);
        }
        if (phase == "PyInstaller") {
            string output = args[Array.IndexOf(args, "--distpath") + 1];
            File.WriteAllText(Path.Combine(output, "setup-odbc.exe"), "verified candidate placeholder");
        }
        if (phase == "publish") {
            if (File.Exists(args[3])) File.Replace(args[2], args[3], null);
            else File.Move(args[2], args[3]);
        }
        return 0;
    }
}
''', encoding="utf-8")
    exe = folder / "fake-python.exe"
    compile_script = folder / "compile.ps1"
    compile_script.write_text("param($Source, $Output)\n$ErrorActionPreference='Stop'\n"
                              "Add-Type -Path $Source -OutputAssembly $Output -OutputType ConsoleApplication\n", encoding="utf-8")
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(compile_script), str(source), str(exe)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    return exe


@pytest.mark.parametrize("existing,failure", [
    (existing, failure)
    for existing in (False, True)
    for failure in ("", "venv", "version", "pip", "tests", "PyInstaller", "smoke", "publish")
    if not (existing and failure == "venv")
])
def test_build_order_and_publication_preservation(tmp_path, fake_python, existing, failure):
    project = tmp_path / "repository with spaces" / "tools" / "setup-odbc"
    project.mkdir(parents=True)
    script = project / "build.ps1"
    shutil.copyfile(Path(__file__).parents[1] / "build.ps1", script)
    (project / "src").mkdir()
    (project / "src" / "run.py").write_text("# entry point", encoding="utf-8")
    previous = project.parent / "setup-odbc.exe"
    previous.write_bytes(b"previous verified executable")
    if existing:
        python = project / ".venv" / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        shutil.copyfile(fake_python, python)
    log = tmp_path / "build-calls.txt"
    env = {**os.environ, "BUILD_TEST_LOG": str(log), "BUILD_TEST_FAIL": failure}
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Python", str(fake_python)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=45)
    phases = log.read_text(encoding="utf-8").splitlines()[::2]
    expected = ([] if existing else ["venv"]) + ["version", "pip", "tests", "PyInstaller", "smoke", "publish"]
    if failure:
        expected = expected[:expected.index(failure) + 1]
        assert result.returncode != 0
        assert previous.read_bytes() == b"previous verified executable"
    else:
        assert result.returncode == 0, result.stderr
        assert previous.read_bytes() == b"verified candidate placeholder"
    assert phases == expected
    if "PyInstaller" in phases:
        assert str(project / "src" / "run.py") in log.read_text(encoding="utf-8")
    assert not (project / "dist").exists()
    assert not list(project.rglob("*.zip"))
    assert not list((project / "build").glob("candidate-*"))
