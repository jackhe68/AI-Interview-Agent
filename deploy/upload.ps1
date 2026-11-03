# Upload code only. Configuration and persistent data stay on the server.
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9.:-]*$')][string]$Server,
    [ValidatePattern('^[A-Za-z_][A-Za-z0-9_-]*$')][string]$User = 'deploy',
    [ValidatePattern('^/(?:[A-Za-z0-9_-][A-Za-z0-9_.-]*/?)+$')][string]$RemoteDir = '/var/www/aiinterview',
    [switch]$PackageOnly
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Invoke-Checked([string]$program, [string[]]$arguments, [string]$failure) {
    $global:LASTEXITCODE = 0
    & $program @arguments
    if ($LASTEXITCODE -ne 0) { throw $failure }
}

try {
    if (-not $PackageOnly -and -not $Server) { throw 'Specify -Server, or use -PackageOnly for local review.' }
    if (-not $PackageOnly) {
        Get-Command scp -ErrorAction Stop | Out-Null
        Get-Command ssh -ErrorAction Stop | Out-Null
    }
    $pythonPath = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = 'python' }
    $releaseId = [guid]::NewGuid().ToString('N')
    $archivePath = Join-Path $root ('.test-artifacts\releases\' + $releaseId + '.tar.gz')
    $builder = Join-Path $PSScriptRoot 'package_release.py'
    Write-Host '==> Build and verify a code-only release; runtime data is excluded.'
    Invoke-Checked $pythonPath @($builder,'--output',$archivePath) 'Packaging failed. Nothing was uploaded.'
    if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf) -or (Get-Item -LiteralPath $archivePath).Length -eq 0) {
        throw 'The release archive was not created. Nothing was uploaded.'
    }
    Invoke-Checked $pythonPath @($builder,'--verify',$archivePath) 'Archive verification failed. Nothing was uploaded.'
    if ($PackageOnly) {
        Write-Host ('Local release verified: ' + $archivePath)
        exit 0
    }
    $hostName = if ($Server.Contains(':')) { '[' + $Server + ']' } else { $Server }
    $remoteArchive = '/tmp/ai-interview-' + $releaseId + '.tar.gz'
    Write-Host '==> Upload the verified code archive.'
    Invoke-Checked 'scp' @($archivePath,($User + '@' + $hostName + ':' + $remoteArchive)) 'Upload failed. Server files were not extracted.'
    # Inputs are restricted to plain host/user/absolute-path characters above.
    # No recursive ownership or permission changes to existing runtime data.
    $command = "sudo -n mkdir -p -- '$RemoteDir' && sudo -n tar --no-same-owner -xzf '$remoteArchive' -C '$RemoteDir' && rm -f -- '$remoteArchive'"
    Invoke-Checked 'ssh' @(($User + '@' + $hostName),$command) 'Server extraction failed. Do not restart until the failure is resolved.'
    Write-Host 'Code upload completed. No service was restarted and no database was restored.'
    Write-Host 'For first installation, configure the server separately and follow deploy/README.md.'
} catch {
    Write-Host ('Release failed: ' + $_.Exception.Message)
    exit 1
}
