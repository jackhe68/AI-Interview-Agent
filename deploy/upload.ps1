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

Write-Host "==> 打包（排除 .venv / .public-test / __pycache__ / .git）"
Push-Location $root
try {
    if (Test-Path "deploy\app.tar.gz") { Remove-Item "deploy\app.tar.gz" -Force }
    tar -czf "deploy\app.tar.gz" `
        --exclude=.venv --exclude=.public-test --exclude=__pycache__ `
        --exclude=.git --exclude="deploy/app.tar.gz" .
}
finally { Pop-Location }

$size = [math]::Round((Get-Item "$root\deploy\app.tar.gz").Length / 1MB, 1)
Write-Host "    包大小 $size MB（含 models/ 约 356MB 情绪模型）"

Write-Host "==> 上传到 $User@$Server"
scp "$root\deploy\app.tar.gz" "${User}@${Server}:/tmp/app.tar.gz"

Write-Host "==> 解包到 $RemoteDir"
ssh "${User}@${Server}" "sudo mkdir -p $RemoteDir && sudo tar -xzf /tmp/app.tar.gz -C $RemoteDir && sudo chown -R ${User}:${User} $RemoteDir && rm -f /tmp/app.tar.gz"

Write-Host "==> 完成。下一步在服务器执行："
Write-Host "    sudo bash $RemoteDir/deploy/bootstrap.sh"
