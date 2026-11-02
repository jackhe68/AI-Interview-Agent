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
    $sources = @('app.py','database.py','speech.py','audio_analysis.py','speech_review.py','public_test.py','api_guard.py','ai_limits.py','candidate_background.py','practice_feedback.py','report_pdf.py','interview_catalog.py','accounts.py','account_migration.py','deletion_journal.py','speech_temp.py','reanswer.py','observability.py','report_jobs.py','tools\run_public_test.py') | ForEach-Object { Join-Path $projectRoot $_ }
    & $pythonPath -m py_compile @sources
    if ($LASTEXITCODE -ne 0) { throw '代码语法检查未通过，未停止原服务。请修复代码后重试。' }
    $shellPath = Join-Path $PSHOME 'powershell.exe'
    if (-not (Test-Path -LiteralPath $shellPath)) { $shellPath = 'powershell.exe' }
    # start_public_test owns the startup lock and decides whether the tracked tunnel is healthy.
    Write-RedeployStatus '【2/4】保留账户和面试记录，检查原公网入口…'
    Write-RedeployStatus '【3/4】更新本机服务；必要时自动重建失效隧道…'
    $startArguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$startScript,'-ReloadApp')
    if ($NoBrowser) { $startArguments += '-NoBrowser' }
    if ($RebuildTunnel) { $startArguments += '-RebuildTunnel' }
    & $shellPath @startArguments
    if ($LASTEXITCODE -ne 0) { throw '公网入口未通过访问检查，请查看上方具体原因。数据已保留；稍后运行“启动公网试用”即可复查，无需反复重新部署。' }
    Write-RedeployStatus '【4/4】重新部署完成！最新网址已更新到桌面，浏览器可直接访问。'
    Write-RedeployStatus '请使用桌面“当前网址”；如果连接已重建，请重新分享新网址。'
    Write-RedeployStatus '现在可以关闭这个窗口。请保持电脑开机、联网且不休眠。'
} catch {
    Write-RedeployStatus ('重新部署未完成：' + $_.Exception.Message)
    Write-RedeployStatus ('数据没有被删除。日志位于：' + (Join-Path $trialFolder 'redeploy.log'))
    exit 1
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
