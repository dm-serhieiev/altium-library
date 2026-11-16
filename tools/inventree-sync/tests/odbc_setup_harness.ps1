param([string]$SetupScript, [string]$ScenarioFile)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
. $SetupScript
$scenario = Get-Content -LiteralPath $ScenarioFile -Raw -Encoding UTF8 | ConvertFrom-Json
$script:dsns = [Collections.ArrayList]::new()
$script:calls = [Collections.ArrayList]::new()
$script:sets = 0
$script:gets = 0
foreach ($dsn in $scenario.dsns) {
    $attributes = @{}
    foreach ($property in $dsn.Attribute.PSObject.Properties) { $attributes[$property.Name] = $property.Value }
    $null = $script:dsns.Add([PSCustomObject]@{ Name=$dsn.Name; DriverName=$dsn.DriverName; Platform=$dsn.Platform; DsnType=$dsn.DsnType; Attribute=$attributes })
}
function Assert-OdbcHost { }
function Get-OdbcDriver {
    [CmdletBinding()]param($Platform)
    if ($scenario.driverError) { throw 'Synthetic Wdac permissions failure' }
    foreach ($driver in $scenario.drivers) {
        $attributes = @{}
        if ($null -ne $driver.Attribute) {
            foreach ($property in $driver.Attribute.PSObject.Properties) { $attributes[$property.Name] = $property.Value }
        }
        [PSCustomObject]@{ Name=$driver.Name; Platform=$driver.Platform; Attribute=$attributes }
    }
}
function Get-OdbcDsn {
    [CmdletBinding()]param($Name, $Platform, $DsnType)
    $script:gets++
    if ($scenario.dsnError) { throw 'Synthetic DSN enumeration failure' }
    $matches = @($script:dsns | Where-Object { $_.Name -eq $Name })
    if ($matches.Count -eq 0) {
        $errorRecord = [Management.Automation.ErrorRecord]::new([Exception]::new('Missing'), 'MI RESULT 6', [Management.Automation.ErrorCategory]::ObjectNotFound, $null)
        $PSCmdlet.ThrowTerminatingError($errorRecord)
    }
    foreach ($dsn in $matches) {
        $copy = [PSCustomObject]@{ Name=$dsn.Name; DriverName=$dsn.DriverName; Platform=$dsn.Platform; DsnType=$dsn.DsnType; Attribute=$dsn.Attribute.Clone() }
        if ($scenario.readbackError -and $script:gets -eq 2) { $copy.Attribute['Database'] = 'Z:\wrong\components.sqlite' }
        $copy
    }
}
function Add-OdbcDsn {
    [CmdletBinding()]param($Name, $Platform, $DsnType, $DriverName, $SetPropertyValue)
    $null = $script:calls.Add('Add')
    if ($scenario.addFailure -eq 'before') { throw 'Synthetic add failure' }
    if ($Name -ne 'AltiumComponents' -or $Platform -ne '64-bit' -or $DsnType -ne 'User') { throw 'Unexpected mutation target' }
    $attributes = @{}
    foreach ($pair in $SetPropertyValue) { $k, $v = $pair -split '=', 2; $attributes[$k] = $v }
    $null = $script:dsns.Add([PSCustomObject]@{ Name=$Name; Platform=$Platform; DsnType=$DsnType; DriverName=$DriverName; Attribute=$attributes })
    if ($scenario.addFailure -eq 'after') { throw 'Synthetic partial add failure' }
}
function Set-OdbcDsn {
    [CmdletBinding()]param($Name, $Platform, $DsnType, $DriverName, $SetPropertyValue, $RemovePropertyValue)
    $script:sets++
    $null = $script:calls.Add('Set')
    if ($scenario.rollbackFailure -and $script:sets -ge 2) { throw 'Synthetic rollback failure' }
    $dsn = $script:dsns | Where-Object { $_.Name -eq $Name -and $_.Platform -eq $Platform -and $_.DsnType -eq $DsnType -and $_.DriverName -eq $DriverName }
    if ($null -eq $dsn -or $Name -ne 'AltiumComponents') { throw 'Unexpected mutation target' }
    foreach ($pair in $SetPropertyValue) { $k, $v = $pair -split '=', 2; $dsn.Attribute[$k] = $v }
    foreach ($key in $RemovePropertyValue) { $dsn.Attribute.Remove($key) }
    if ($scenario.setFailure -and $script:sets -eq 1) { throw 'Synthetic partial set failure' }
}
function Remove-OdbcDsn {
    [CmdletBinding()]param($Name, $Platform, $DsnType)
    $null = $script:calls.Add('Remove')
    if ($scenario.removeFailure) { throw 'Synthetic removal failure' }
    $dsn = $script:dsns | Where-Object { $_.Name -eq $Name -and $_.Platform -eq $Platform -and $_.DsnType -eq $DsnType }
    if ($Name -ne 'AltiumComponents') { throw 'Unexpected mutation target' }
    $script:dsns.Remove($dsn)
}
function Test-AltiumOdbcConnection([string]$DsnName, [string]$DatabasePath) {
    $null = $script:calls.Add('Connect')
    if ($scenario.connectionFailure) { throw 'Synthetic read-only connection failure' }
    if ($DsnName -ne 'AltiumComponents' -or $DatabasePath -ne $scenario.expectedDatabase) { throw 'Incorrect connection target' }
}
$code = 0
$failure = ''
try {
    Invoke-AltiumOdbcSetup -ToolsDirectory (Split-Path -LiteralPath $SetupScript) -SelectedDriver $scenario.driverName -VerifyOnly:([bool]$scenario.checkOnly)
} catch {
    $code = 1
    $failure = $_.Exception.Message
}
$report = @{ code=$code; error=$failure; calls=@($script:calls.ToArray()); dsns=@($script:dsns.ToArray()) }
Write-Output ('RESULT:' + ($report | ConvertTo-Json -Compress -Depth 10))
exit $code
