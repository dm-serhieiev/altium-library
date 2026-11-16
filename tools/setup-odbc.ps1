<#
.SYNOPSIS
Configures the local 64-bit AltiumComponents User DSN for this checkout.
.DESCRIPTION
Requires Windows PowerShell 5.1 and an installed SQLite3 ODBC driver.
Does not install software, contact InvenTree, write database data or edit DbLib.
.PARAMETER CheckOnly
Verify the existing configuration and connection without changing any DSN.
.PARAMETER DriverName
Exact installed name of a compatible SQLite3 ODBC driver (no wildcards).
#>
[CmdletBinding()]
param(
    [string]$DriverName = 'SQLite3 ODBC Driver',
    [switch]$CheckOnly
)

function Assert-OdbcHost {
    if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSEdition -ne 'Desktop' -or
        $PSVersionTable.PSVersion -lt [Version]'5.1') {
        throw 'Run this script using Windows PowerShell 5.1 on Windows 10 or 11.'
    }
    if (-not [Environment]::Is64BitProcess) {
        throw '64-bit Windows PowerShell is required. From 32-bit PowerShell run: & "$env:WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File <path-to-tools\setup-odbc.ps1>.'
    }
    try { Import-Module Wdac -ErrorAction Stop }
    catch { throw 'Cannot load the built-in Windows Wdac module. Run Windows PowerShell 5.1 and check local permissions.' }
}

function Get-AbsoluteDatabasePath([string]$ToolsDirectory) {
    return [IO.Path]::GetFullPath((Join-Path $ToolsDirectory '..\database\components.sqlite'))
}

function Test-EquivalentDatabasePath([string]$Left, [string]$Right) {
    # Do not interpret relative existing DSN paths against this process's cwd.
    $absolute = '^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+[\\/])'
    if ($Left -notmatch $absolute -or $Right -notmatch $absolute) { return $false }
    try { return [String]::Equals([IO.Path]::GetFullPath($Left), [IO.Path]::GetFullPath($Right), [StringComparison]::OrdinalIgnoreCase) }
    catch { return $false }
}

function Open-SqliteSnapshot([string]$DatabasePath) {
    try { $item = Get-Item -LiteralPath $DatabasePath -Force -ErrorAction Stop }
    catch [System.Management.Automation.ItemNotFoundException] {
        throw "SQLite snapshot not found: $DatabasePath. Generate or restore a valid snapshot first; setup never creates a database."
    }
    catch { throw "Cannot inspect SQLite snapshot: $DatabasePath. Check file permissions." }
    if ($item -isnot [IO.FileInfo]) { throw "SQLite snapshot is not a regular file: $DatabasePath" }
    $stream = $null
    try {
        # Hold a read handle without write/delete sharing until verification ends.
        # This keeps the verified snapshot stable and prevents replacement/writes.
        try { $stream = [IO.File]::Open($DatabasePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read) }
        catch { throw "SQLite snapshot is unreadable or in use: $DatabasePath. Check permissions and close Altium and other database consumers." }
        foreach ($suffix in @('-wal', '-shm', '-journal')) {
            $entry = $null
            try { $entry = Get-Item -LiteralPath ($DatabasePath + $suffix) -Force -ErrorAction Stop }
            catch [System.Management.Automation.ItemNotFoundException] { }
            catch { throw "Cannot inspect SQLite journal sidecar: $DatabasePath$suffix. Check file permissions." }
            if ($null -ne $entry) { throw 'SQLite journal sidecar present. Close database consumers and let SQLite finish normal recovery/cleanup; do not delete journals.' }
        }
        $header = New-Object byte[] 100
        if ($stream.Read($header, 0, 100) -ne 100 -or
            [Text.Encoding]::ASCII.GetString($header, 0, 16) -cne "SQLite format 3`0") {
            throw 'Invalid SQLite header. Restore or generate a valid snapshot first.'
        }
        $pageSize = 256 * [int]$header[16] + [int]$header[17]
        if ($pageSize -eq 1) { $pageSize = 65536 }
        if ($pageSize -lt 512 -or $pageSize -gt 65536 -or ($pageSize -band ($pageSize - 1)) -ne 0 -or
            $stream.Length -lt $pageSize -or $stream.Length % $pageSize -ne 0) {
            throw 'Invalid or truncated SQLite snapshot (page size/file length).'
        }
        return $stream
    } catch {
        if ($null -ne $stream) { $stream.Dispose() }
        if ($_.Exception -is [IO.IOException] -or $_.Exception -is [UnauthorizedAccessException]) {
            throw "SQLite snapshot is unreadable or in use: $DatabasePath. Check permissions and close Altium and other database consumers."
        }
        throw
    }
}

function Get-AltiumDsn([string]$DsnName) {
    try { return @(Get-OdbcDsn -Name $DsnName -DsnType All -Platform All -ErrorAction Stop) }
    catch {
        # Wdac reports an absent DSN as MI_RESULT_NOT_FOUND. Other CIM failures
        # (notably permission failures) must never be treated as an absent DSN.
        if ($_.FullyQualifiedErrorId -like 'MI RESULT 6,*' -and $_.CategoryInfo.Category -eq 'ObjectNotFound') { return @() }
        throw "Cannot inspect ODBC DSN '$DsnName'. Check Windows ODBC permissions and Wdac availability."
    }
}

function Get-CompatibleAltiumDsn([string]$DsnName, [string]$SelectedDriver) {
    $all = @(Get-AltiumDsn $DsnName)
    if ($all.Count -eq 0) { return $null }
    $user = @($all | Where-Object { $_.DsnType -eq 'User' -and $_.Platform -eq '64-bit' -and $_.DriverName -eq $SelectedDriver })
    $conflict = $user.Count -ne 1
    foreach ($dsn in $all) {
        if ($dsn.DsnType -ne 'User' -or $dsn.DriverName -ne $SelectedDriver) { $conflict = $true }
        if ($dsn.Platform -ne '64-bit') {
            # User DSNs share a registry namespace across bitness. A matching
            # 32-bit view is allowed only alongside the same verified 64-bit DSN.
            if ($dsn.Platform -ne '32-bit' -or $user.Count -ne 1 -or
                -not (Test-EquivalentDatabasePath $dsn.Attribute['Database'] $user[0].Attribute['Database'])) { $conflict = $true }
        }
    }
    if ($conflict) {
        throw "Conflicting DSN '$DsnName': expected only a compatible 64-bit User DSN. Resolve/rename the incompatible User or System DSN explicitly in ODBC Data Sources before retrying. No conflicting DSN is overwritten."
    }
    # These options can write logs, load code, attach other databases or change
    # journal settings while connecting. Do not execute them during verification.
    foreach ($key in @('TraceFile', 'LoadExt', 'AttachAs', 'JournalMode', 'SyncPragma')) {
        if (-not [String]::IsNullOrWhiteSpace([string]$user[0].Attribute[$key])) {
            throw "Conflicting DSN option '$key' in '$DsnName'. Resolve it explicitly in ODBC Data Sources; setup will not change it."
        }
    }
    return $user[0]
}

function New-AltiumReadOnlyConnection([string]$DsnName, [string]$DatabasePath) {
    # The SQLite3 driver ignores SQL_ATTR_ACCESS_MODE. Use its SQLite URI
    # support instead. The DSN's plain absolute path was independently read back.
    # immutable is safe here only while Open-SqliteSnapshot holds the read guard
    # and has rejected journals; it also prevents WAL/SHM creation during a check.
    $uri = [Uri]::new($DatabasePath)
    $fileUri = $uri.AbsoluteUri
    if ($uri.IsUnc) { $fileUri = 'file:////' + $uri.Host + $uri.AbsolutePath }
    $builder = [System.Data.Odbc.OdbcConnectionStringBuilder]::new()
    $builder['DSN'] = $DsnName
    $builder['Database'] = $fileUri + '?mode=ro&immutable=1'
    $builder['NoCreat'] = '1'
    $builder['Timeout'] = '5000'
    return [System.Data.Odbc.OdbcConnection]::new($builder.ConnectionString)
}

function Test-AltiumOdbcConnection([string]$DsnName, [string]$DatabasePath) {
    $connection = New-AltiumReadOnlyConnection $DsnName $DatabasePath
    $command = $null
    $reader = $null
    try {
        $connection.Open()
        $command = $connection.CreateCommand()
        $command.CommandTimeout = 5
        $command.CommandText = 'SELECT name FROM sqlite_master LIMIT 1'
        $null = $command.ExecuteScalar()
        $command.CommandText = 'PRAGMA database_list'
        $reader = $command.ExecuteReader()
        $matched = $false
        while ($reader.Read()) {
            if ($reader.GetString(1) -eq 'main') {
                $matched = Test-EquivalentDatabasePath $reader.GetString(2) $DatabasePath
            }
        }
        if (-not $matched) { throw 'ODBC opened a different database.' }
    } catch {
        # Do not print driver messages or connection strings that could expose
        # unrelated existing DSN settings. Context is the selected name/path only.
        throw "Read-only ODBC connection test failed for '$DsnName' and '$DatabasePath'. Check the driver, file permissions and SQLite snapshot integrity."
    } finally {
        if ($null -ne $reader) { $reader.Dispose() }
        if ($null -ne $command) { $command.Dispose() }
        $connection.Dispose()
    }
}

function Invoke-AltiumOdbcSetup {
    param(
        [Parameter(Mandatory=$true)][string]$ToolsDirectory,
        [string]$SelectedDriver = 'SQLite3 ODBC Driver',
        [switch]$VerifyOnly,
        # Internal seam for isolated integration tests; the public CLI fixes the name.
        [string]$DsnName = 'AltiumComponents'
    )
    Assert-OdbcHost
    if ([String]::IsNullOrWhiteSpace($SelectedDriver) -or $SelectedDriver -notmatch 'SQLite' -or
        [System.Management.Automation.WildcardPattern]::ContainsWildcardCharacters($SelectedDriver)) {
        throw 'DriverName must be the exact installed name of a compatible SQLite3 ODBC driver, without wildcards.'
    }
    Write-Host "Altium SQLite ODBC Setup`n------------------------"
    $database = Get-AbsoluteDatabasePath $ToolsDirectory
    if ($database.Contains(';')) {
        throw "The SQLite3 ODBC setup interface truncates paths at a semicolon. Move this checkout to a path without ';' before configuring the DSN. No DSN changed."
    }
    Write-Host "`nRepository:`n$([IO.Path]::GetDirectoryName([IO.Path]::GetDirectoryName($database)))`n`nDatabase:`n$database"
    $snapshot = Open-SqliteSnapshot $database
    try {
        try { $drivers = @(Get-OdbcDriver -Platform All -ErrorAction Stop | Where-Object { $_.Name -like '*SQLite*' }) }
        catch { throw 'Cannot enumerate SQLite ODBC drivers. Check Windows ODBC permissions and Wdac availability.' }
        Write-Host "`nDetected SQLite ODBC drivers:"
        if ($drivers.Count -eq 0) { Write-Host '(none)' }
        foreach ($driver in $drivers) { Write-Host ("{0} ({1})" -f $driver.Name, $driver.Platform) }
        $selected = @($drivers | Where-Object { $_.Name -eq $SelectedDriver -and $_.Platform -eq '64-bit' })
        if ($selected.Count -ne 1) {
            throw "Required 64-bit driver '$SelectedDriver' is unavailable. Install the trusted 64-bit SQLite3 ODBC driver (sqliteodbc_w64.exe from https://www.ch-werner.de/sqliteodbc/) separately, then rerun setup. No software is downloaded or installed by this script."
        }
        if ([IO.Path]::GetFileName([string]$selected[0].Attribute['Driver']) -ine 'sqlite3odbc.dll') {
            throw "Selected driver '$SelectedDriver' is not the supported SQLite3 ODBC implementation (sqlite3odbc.dll). No DSN changed."
        }
        Write-Host "`nODBC Driver:`n$SelectedDriver (64-bit)`n`nDSN:`n$DsnName (User)"
        $previous = Get-CompatibleAltiumDsn $DsnName $SelectedDriver
        $samePath = $null -ne $previous -and (Test-EquivalentDatabasePath $previous.Attribute['Database'] $database)
        if ($VerifyOnly -and -not $samePath) {
            throw "DSN '$DsnName' is missing or points to another database. Run setup without -CheckOnly to configure it. No changes made."
        }
        $attempted = $false
        $observed = $null
        $status = 'Already configured. No changes required.'
        try {
            if (-not $samePath) {
                $attempted = $true
                try {
                    if ($null -eq $previous) {
                        Add-OdbcDsn -Name $DsnName -DsnType User -Platform '64-bit' -DriverName $SelectedDriver -SetPropertyValue @("Database=$database", 'NoCreat=1') -ErrorAction Stop | Out-Null
                        $status = 'New User DSN created.'
                    } else {
                        Set-OdbcDsn -Name $DsnName -DsnType User -Platform '64-bit' -DriverName $SelectedDriver -SetPropertyValue @("Database=$database") -ErrorAction Stop | Out-Null
                        $status = 'Existing DSN updated.'
                    }
                } catch { throw "ODBC configuration failed for '$DsnName'. Check User DSN permissions and the selected driver's installation." }
            }
            $current = Get-CompatibleAltiumDsn $DsnName $SelectedDriver
            $observed = $current
            if ($null -eq $current -or -not (Test-EquivalentDatabasePath $current.Attribute['Database'] $database)) {
                throw "ODBC configuration read-back failed for '$DsnName': expected database path was not retained."
            }
            Test-AltiumOdbcConnection $DsnName $database
        } catch {
            $failure = $_.Exception.Message
            if ($attempted) {
                try {
                    $current = Get-CompatibleAltiumDsn $DsnName $SelectedDriver
                    if ($null -ne $previous) {
                        if ($null -eq $current) { throw 'DSN disappeared during setup.' }
                        if ($current.Attribute['Database'] -cne $previous.Attribute['Database']) {
                            if (-not (Test-EquivalentDatabasePath $current.Attribute['Database'] $database) -and
                                ($null -eq $observed -or $current.Attribute['Database'] -cne $observed.Attribute['Database'])) { throw 'DSN changed concurrently; not overwriting it.' }
                            if ($previous.Attribute.ContainsKey('Database')) {
                                Set-OdbcDsn -Name $DsnName -DsnType User -Platform '64-bit' -DriverName $SelectedDriver -SetPropertyValue @("Database=$($previous.Attribute['Database'])") -ErrorAction Stop | Out-Null
                            } else {
                                Set-OdbcDsn -Name $DsnName -DsnType User -Platform '64-bit' -DriverName $SelectedDriver -RemovePropertyValue @('Database') -ErrorAction Stop | Out-Null
                            }
                        }
                        $restored = Get-CompatibleAltiumDsn $DsnName $SelectedDriver
                        if ($null -eq $restored -or $restored.Attribute['Database'] -cne $previous.Attribute['Database']) { throw 'Rollback read-back mismatch.' }
                        $failure += ' Previous DSN database setting restored.'
                    } elseif ($null -ne $current) {
                        if (-not (Test-EquivalentDatabasePath $current.Attribute['Database'] $database) -and
                            ($null -eq $observed -or $current.Attribute['Database'] -cne $observed.Attribute['Database'])) { throw 'DSN changed concurrently; not removing it.' }
                        Remove-OdbcDsn -Name $DsnName -DsnType User -Platform '64-bit' -ErrorAction Stop
                        if (@(Get-AltiumDsn $DsnName).Count -ne 0) { throw 'Rollback removal failed.' }
                        $failure += ' Newly created DSN removed.'
                    }
                } catch { $failure += " Rollback incomplete; inspect '$DsnName' in 64-bit ODBC Data Sources before retrying." }
            }
            throw $failure
        }
        Write-Host "`nStatus:`n$status`n`nConnection test:`nSuccessful.`n`nAltium database connection is ready."
    } finally { $snapshot.Dispose() }
}

# Dot-sourcing defines functions for offline tests without executing setup.
if ($MyInvocation.InvocationName -ne '.') {
    try {
        Invoke-AltiumOdbcSetup -ToolsDirectory $PSScriptRoot -SelectedDriver $DriverName -VerifyOnly:$CheckOnly
        exit 0
    } catch {
        [Console]::Error.WriteLine("ODBC setup failed: " + $_.Exception.Message)
        exit 1
    }
}
