param([switch]$NoBrowser, [switch]$RebuildTunnel)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$trialFolder = Join-Path $projectRoot '.public-test'
New-Item -ItemType Directory -Force -Path $trialFolder | Out-Null
$mutex = New-Object System.Threading.Mutex($false, 'Local\AIInterviewPublicTrialRedeploy')
$held = $false
function Write-RedeployStatus([string]$message) {
    Write-Host $message
    ('[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $message) | Add-Content -LiteralPath (Join-Path $trialFolder 'redeploy.log') -Encoding utf8
}
try {
    try { $held = $mutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) {
        Write-Host '另一个重新部署任务正在运行，请等待原窗口完成。'
        exit 0
    }
    Write-RedeployStatus '【1/4】检查项目文件和语法…'
    $pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
    $startScript = Join-Path $PSScriptRoot 'start_public_test.ps1'
    $stopScript = Join-Path $PSScriptRoot 'stop_public_test.ps1'
    foreach ($path in @($pythonPath, $startScript, $stopScript, (Join-Path $trialFolder 'cloudflared.exe'))) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw ('缺少运行文件：' + $path) }
    }
    $sources = @('app.py','database.py','speech.py','audio_analysis.py','speech_review.py','public_test.py','api_guard.py','ai_limits.py','candidate_background.py','practice_feedback.py','report_pdf.py','interview_catalog.py','tools\run_public_test.py') | ForEach-Object { Join-Path $projectRoot $_ }
    & $pythonPath -m py_compile @sources
    if ($LASTEXITCODE -ne 0) { throw '代码语法检查未通过，未停止原服务。请修复代码后重试。' }
    $shellPath = Join-Path $PSHOME 'powershell.exe'
    if (-not (Test-Path -LiteralPath $shellPath)) { $shellPath = 'powershell.exe' }
    $keepTunnel = $false
    try {
        $saved = Get-Content -LiteralPath (Join-Path $trialFolder 'processes.json') -Raw | ConvertFrom-Json
        $tunnel = Get-Process -Id ([int]$saved.tunnel_pid) -ErrorAction Stop
        $expected = [datetime]::Parse($saved.tunnel_started).ToUniversalTime()
        if (-not $RebuildTunnel -and [math]::Abs(($tunnel.StartTime.ToUniversalTime()-$expected).TotalSeconds) -lt 1 -and
            $saved.public_url -match '^https://[a-z0-9-]+\.trycloudflare\.com$') {
            # Do not discard a live shared URL because a single probe timed out.
            # start_public_test still requires live HTTPS success before publishing.
            $keepTunnel = $true
        }
    } catch { $keepTunnel = $false }
    if ($keepTunnel) {
        Write-RedeployStatus '【2/4】保留可用的公网隧道和原网址，仅更新面试服务…'
        & $shellPath -NoProfile -ExecutionPolicy Bypass -File $stopScript -KeepTunnel
    } else {
        Write-RedeployStatus '【2/4】原公网入口不可用，重建连接并保留面试数据…'
        & $shellPath -NoProfile -ExecutionPolicy Bypass -File $stopScript
    }
    if ($LASTEXITCODE -ne 0) { throw '停止旧服务未完成，请查看运行日志后重试。' }
    Write-RedeployStatus '【3/4】重新加载当前项目并建立公网入口…'
    $startArguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$startScript)
    if ($NoBrowser) { $startArguments += '-NoBrowser' }
    if ($keepTunnel) { $startArguments += '-KeepTunnel' }
    & $shellPath @startArguments
    if ($LASTEXITCODE -ne 0) { throw '公网入口未通过实时访问检查。请检查网络后再次双击重新部署。' }
    Write-RedeployStatus '【4/4】重新部署完成！最新网址已更新到桌面，浏览器可直接访问。'
    if ($keepTunnel) { Write-RedeployStatus '原网址已保留，无需重新分享。' }
    else { Write-RedeployStatus '公网入口已重建，请使用桌面当前网址重新分享。' }
    Write-RedeployStatus '现在可以关闭这个窗口。请保持电脑开机、联网且不休眠。'
} catch {
    Write-RedeployStatus ('重新部署未完成：' + $_.Exception.Message)
    Write-RedeployStatus ('数据没有被删除。日志位于：' + (Join-Path $trialFolder 'redeploy.log'))
    exit 1
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
