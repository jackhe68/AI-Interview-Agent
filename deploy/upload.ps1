# 从 Windows 上传代码到服务器：.
#   powershell -ExecutionPolicy Bypass -File deploy\upload.ps1 -Server 47.x.x.x
# 前提：本机已能 ssh deploy@服务器（已配公钥）
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [string]$User = "deploy",
    [string]$RemoteDir = "/var/www/aiinterview"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "==> Build a code-only release; runtime files stay on the server."
$pythonPath = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = 'python' }
$releaseId = [guid]::NewGuid().ToString('N')
$archivePath = Join-Path $root ('.test-artifacts\releases\' + $releaseId + '.tar.gz')
& $pythonPath (Join-Path $PSScriptRoot 'package_release.py') --output $archivePath
if ($LASTEXITCODE -ne 0) { throw 'Code-only release packaging failed. Nothing was uploaded.' }

$size = [math]::Round((Get-Item -LiteralPath $archivePath).Length / 1MB, 1)
Write-Host "    Code release: $size MB; no database, credentials, uploads or model cache."

Write-Host "==> 上传到 $User@$Server"
scp $archivePath "${User}@${Server}:/tmp/app.tar.gz"

Write-Host "==> 解包到 $RemoteDir"
ssh "${User}@${Server}" "sudo mkdir -p $RemoteDir && sudo tar -xzf /tmp/app.tar.gz -C $RemoteDir && sudo chown -R ${User}:${User} $RemoteDir && rm -f /tmp/app.tar.gz"

Write-Host "==> 完成。下一步在服务器执行："
Write-Host "    sudo bash $RemoteDir/deploy/bootstrap.sh"
