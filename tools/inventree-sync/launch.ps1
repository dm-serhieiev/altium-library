param(
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$ForwardArgs
)

# A new Explorer /c console has only cmd and this helper attached. Existing
# terminals have another attached process, or their parent cmd was not /c.
# Redirected/automated invocations never pause.
$pauseAfterRun = $false
try {
    if (-not [Console]::IsInputRedirected -and -not [Console]::IsOutputRedirected) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SyncConsole {
    [DllImport("kernel32.dll")]
    public static extern uint GetConsoleProcessList(uint[] list, uint count);
}
'@
        $consoleProcesses = New-Object uint32[] 16
        $count = [SyncConsole]::GetConsoleProcessList($consoleProcesses, 16)
        $selfProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$PID"
        $parentProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($selfProcess.ParentProcessId)"
        $pauseAfterRun = $count -gt 0 -and $count -le 2 -and $parentProcess.Name -ieq 'cmd.exe' -and $parentProcess.CommandLine -match '(?i)\s/c\s'
    }
} catch {
    # If console detection is unavailable, avoid blocking terminal automation.
    $pauseAfterRun = $false
}

$syncExit = 4
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    [Console]::Error.WriteLine("Missing executable: $Executable")
    [Console]::Error.WriteLine('Download the Windows artifact into this repository, or build it with tools\inventree-sync\build.ps1.')
} else {
    & $Executable @ForwardArgs
    $syncExit = $LASTEXITCODE
}
if ($pauseAfterRun) {
    Read-Host 'Press Enter to close this window' | Out-Null
}
exit $syncExit
