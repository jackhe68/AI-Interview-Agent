param([switch]$KeepTunnel)
$ErrorActionPreference = 'Stop'
$trialFolder = Join-Path (Split-Path -Parent $PSScriptRoot) '.public-test'
$statePath = Join-Path $trialFolder 'processes.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'Public trial is already stopped.'; exit 0 }
$object = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$state = @{}
$object.PSObject.Properties | ForEach-Object { $state[$_.Name] = $_.Value }
function Stop-TrialProcessTree([int]$processId, [datetime]$rootStarted) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$processId" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.CreationDate.ToUniversalTime() -ge $rootStarted.AddSeconds(-1)) {
            Stop-TrialProcessTree ([int]$_.ProcessId) $rootStarted
        }
    }
    Stop-Process -Id $processId -ErrorAction SilentlyContinue
}
$kinds = @('tunnel','server')
if ($KeepTunnel) { $kinds = @('server') }
foreach ($kind in $kinds) {
    if (-not $state.ContainsKey($kind + '_pid')) { continue }
    try {
        $process = Get-Process -Id ([int]$state[$kind + '_pid']) -ErrorAction Stop
        $expectedStart = [datetime]::Parse($state[$kind + '_started']).ToUniversalTime()
        if ([math]::Abs(($process.StartTime.ToUniversalTime() - $expectedStart).TotalSeconds) -lt 1) {
            Stop-TrialProcessTree $process.Id $expectedStart
        }
    } catch { }
}
if (-not $KeepTunnel) { $state.Remove('public_url') }
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
if ($KeepTunnel) {
    Write-Host 'Trial application stopped; the public tunnel and URL are preserved.'
} else {
    Write-Host 'Public trial stopped. Interview data is preserved; local port 5001 is unchanged.'
}
