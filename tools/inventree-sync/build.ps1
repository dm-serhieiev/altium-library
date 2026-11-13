param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Build the Windows executable on Windows.' }
$repository = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$buildEnvironment = Join-Path $PSScriptRoot '.venv-build'
$buildPython = Join-Path $buildEnvironment 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    & $Python -m venv $buildEnvironment
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create the build environment.' }
}
& $buildPython -c 'import sys; sys.exit(sys.version_info < (3, 11))'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
& $buildPython -m pip install -e "${PSScriptRoot}[test,build]"
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
& $buildPython -m pytest (Join-Path $PSScriptRoot 'tests') -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; executable was not built.' }

$output = Join-Path $PSScriptRoot 'dist'
$work = Join-Path $PSScriptRoot 'build'
& $buildPython -m PyInstaller --onefile --console --noconfirm --name inventree-sync --distpath $output --workpath $work --specpath $work --paths (Join-Path $PSScriptRoot 'src') (Join-Path $PSScriptRoot 'run.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
$executable = Join-Path $output 'inventree-sync.exe'
& $buildPython -m pytest (Join-Path $PSScriptRoot 'tests\test_packaging.py') --sync-executable $executable -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw 'Executable smoke tests failed.' }

# Bundle only maintained launch/config sources and the generated executable.
# No local config, credentials or component data enter the downloadable archive.
$bundle = Join-Path $work ('bundle-' + [Guid]::NewGuid().ToString('N'))
$bundleTool = Join-Path $bundle 'tools\inventree-sync'
New-Item -ItemType Directory -Force -Path (Join-Path $bundleTool 'dist') | Out-Null
Copy-Item -LiteralPath $executable -Destination (Join-Path $bundleTool 'dist\inventree-sync.exe')
foreach ($source in @('config.example.toml', 'launch.ps1', 'README.md')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $source) -Destination (Join-Path $bundleTool $source)
}
Copy-Item -LiteralPath (Join-Path $repository 'sync.cmd') -Destination (Join-Path $bundle 'sync.cmd')
$archive = Join-Path $output 'inventree-sync-windows.zip'
Compress-Archive -Path (Join-Path $bundle '*') -DestinationPath $archive -Force
Write-Host "Executable: $executable"
Write-Host "Repository overlay artifact: $archive"
exit 0
