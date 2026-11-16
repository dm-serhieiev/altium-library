param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Build the Windows executable on Windows.' }
$project = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$toolsDirectory = (Resolve-Path -LiteralPath (Join-Path $project '..')).Path
$environment = Join-Path $project '.venv'
$buildPython = Join-Path $environment 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython -PathType Leaf)) {
    & $Python -m venv $environment
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create .venv.' }
}
& $buildPython -c 'import sys; sys.exit(sys.version_info < (3, 11))'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required; recreate .venv with a supported Python.' }
& $buildPython -m pip install -e "${project}[test,build]"
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
& $buildPython -m pytest (Join-Path $project 'tests') -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; executable was not built.' }

# Build a separate candidate; never remove the published executable first.
$work = [IO.Path]::GetFullPath((Join-Path $project 'build'))
$candidate = [IO.Path]::GetFullPath((Join-Path $work ('candidate-' + [Guid]::NewGuid().ToString('N'))))
if (-not $candidate.StartsWith($work + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Candidate directory is outside build.'
}
New-Item -ItemType Directory -Path $candidate -Force | Out-Null
try {
    & $buildPython -m PyInstaller --onefile --console --noconfirm --name inventree-sync --distpath $candidate --workpath (Join-Path $candidate 'work') --specpath $candidate --paths (Join-Path $project 'src') (Join-Path $project 'src\run.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed; published executable was preserved.' }
    $executable = Join-Path $candidate 'inventree-sync.exe'
    & $buildPython -m pytest (Join-Path $project 'tests\test_packaging.py') --sync-executable $executable -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'Executable smoke tests failed; published executable was preserved.' }
    $destination = Join-Path $toolsDirectory 'inventree-sync.exe'
    # Same-volume atomic replacement, including when a running exe blocks it.
    # No delete/copy fallback; Python is used only during building.
    & $buildPython -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' $executable $destination
    if ($LASTEXITCODE -ne 0) { throw 'Cannot publish executable; close running inventree-sync instances and retry. Previous executable was preserved.' }
    Write-Host "Executable: $destination"
} finally {
    # This invocation owns only this unique, checked build subdirectory.
    if (Test-Path -LiteralPath $candidate) {
        try { Remove-Item -LiteralPath $candidate -Recurse -Force }
        catch { Write-Warning "Cannot clean build candidate directory: $candidate" }
    }
}
exit 0
