param([string]$SetupScript, [string]$OriginalTools, [string]$MovedTools, [string]$InvalidTools)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
. $SetupScript
Assert-OdbcHost
$drivers = @(Get-OdbcDriver -Platform '64-bit' | Where-Object { $_.Name -eq 'SQLite3 ODBC Driver' })
if ($drivers.Count -ne 1) { Write-Output 'SQLite3 64-bit ODBC driver unavailable'; exit 77 }
$name = 'AltiumTest-' + [Guid]::NewGuid().ToString('N').Substring(0,16)
$database = Get-AbsoluteDatabasePath $MovedTools
try {
    # All mutations use this unpredictable, disposable User DSN, never AltiumComponents.
    Invoke-AltiumOdbcSetup -ToolsDirectory $OriginalTools -DsnName $name
    Invoke-AltiumOdbcSetup -ToolsDirectory $OriginalTools -DsnName $name
    Invoke-AltiumOdbcSetup -ToolsDirectory $MovedTools -DsnName $name
    Invoke-AltiumOdbcSetup -ToolsDirectory $MovedTools -DsnName $name -VerifyOnly
    $prior = (Get-CompatibleAltiumDsn $name 'SQLite3 ODBC Driver').Attribute.Clone()
    if ($prior['NoCreat'] -ne '1') { throw 'Move lost a pre-existing DSN setting.' }
    $rejected = $false
    try { Invoke-AltiumOdbcSetup -ToolsDirectory $InvalidTools -DsnName $name }
    catch { $rejected = $_.Exception.Message.Contains('Previous DSN database setting restored.') }
    if (-not $rejected) { throw 'Corrupt snapshot did not trigger a verified rollback.' }
    $restored = (Get-CompatibleAltiumDsn $name 'SQLite3 ODBC Driver').Attribute
    foreach ($key in $prior.Keys) {
        if ($restored[$key] -cne $prior[$key]) { throw 'Rollback changed the previous DSN configuration.' }
    }
    $guard = Open-SqliteSnapshot $database
    $connection = New-AltiumReadOnlyConnection $name $database
    $command = $null
    try {
        $connection.Open()
        $command = $connection.CreateCommand()
        $command.CommandText = "INSERT INTO parts VALUES ('must-not-be-written')"
        $rejected = $false
        try { $null = $command.ExecuteNonQuery() }
        catch [System.Data.Odbc.OdbcException] { $rejected = $true }
        if (-not $rejected) { throw 'The test connection was writable.' }
    } finally {
        if ($null -ne $command) { $command.Dispose() }
        $connection.Dispose()
        $guard.Dispose()
    }
    # NoCreat/URI must also reject a missing file without creating anything.
    $missing = Join-Path (Split-Path -LiteralPath $database) 'must-not-be-created.sqlite'
    $connection = New-AltiumReadOnlyConnection $name $missing
    try {
        $rejected = $false
        try { $connection.Open() }
        catch [System.Data.Odbc.OdbcException] { $rejected = $true }
        if (-not $rejected -or (Test-Path -LiteralPath $missing)) { throw 'Missing database was not rejected.' }
    } finally { $connection.Dispose() }
    Write-Output 'INTEGRATION: create, repeat, move, check, rollback, read-only and no-create passed.'
} finally {
    $owned = @(Get-AltiumDsn $name)
    if ($owned.Count -gt 0) { Remove-OdbcDsn -Name $name -DsnType User -Platform '64-bit' -ErrorAction Stop }
    if (@(Get-AltiumDsn $name).Count -ne 0) { throw 'Temporary integration DSN cleanup failed.' }
}
