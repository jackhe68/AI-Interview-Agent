param([switch]$NoBrowser, [switch]$KeepTunnel, [switch]$ReloadApp, [switch]$RebuildTunnel)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$trialFolder = Join-Path $projectRoot '.public-test'
$statePath = Join-Path $trialFolder 'processes.json'
New-Item -ItemType Directory -Force -Path $trialFolder | Out-Null
$startupMutex = New-Object System.Threading.Mutex($false, 'Local\AIInterviewPublicTrialStartup')
$startupHeld = $false

function Write-TrialStatus([string]$message) {
    Write-Host $message
    ('[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $message) | Add-Content -LiteralPath (Join-Path $trialFolder 'startup.log') -Encoding utf8
}
function Read-ConnectedUrl {
    # The saved URL belongs to the tracked process. A shared legacy log may belong to another run.
    if ($state.ContainsKey('public_url') -and $state['public_url'] -match '^https://[a-z0-9-]+\.trycloudflare\.com$') {
        return $state['public_url']
    }
    if (-not $state.ContainsKey('tunnel_log')) { return $null }
    $logPath = [IO.Path]::GetFullPath($state['tunnel_log'])
    $runtimeRoot = [IO.Path]::GetFullPath($trialFolder).TrimEnd('\') + '\'
    if (-not $logPath.StartsWith($runtimeRoot,[StringComparison]::OrdinalIgnoreCase)) { return $null }
    if (-not (Test-Path -LiteralPath $logPath)) { return $null }
    $text = Get-Content -LiteralPath $logPath -Raw -ErrorAction SilentlyContinue
    if (-not $text -or -not $text.Contains('Registered tunnel connection')) { return $null }
    $urls = [regex]::Matches($text, 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($urls.Count) { return $urls[$urls.Count - 1].Value }
    return $null
}
function Save-TrialState {
    $temporary = Join-Path $trialFolder ('state-' + [guid]::NewGuid().ToString('N') + '.tmp')
    $state | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $statePath -Force
}
function Start-NewTrialTunnel {
    $generation = [guid]::NewGuid().ToString('N')
    $state.Remove('public_url')
    $state['tunnel_log'] = Join-Path $trialFolder ('tunnel-' + $generation + '.err.log')
    $state['tunnel_out_log'] = Join-Path $trialFolder ('tunnel-' + $generation + '.out.log')
    $process = Start-Process -FilePath $tunnelPath -ArgumentList 'tunnel','--url','http://127.0.0.1:5010','--protocol','http2','--edge-ip-version','4','--no-autoupdate' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $state['tunnel_out_log'] -RedirectStandardError $state['tunnel_log'] -PassThru
    $state['tunnel_pid'] = $process.Id
    $state['tunnel_started'] = $process.StartTime.ToUniversalTime().ToString('o')
    Save-TrialState
    return $process
}
function Test-PublicTrialUrl([string]$url) {
    if ($url -notmatch '^https://[a-z0-9-]+\.trycloudflare\.com$') { return $false }
    try {
        $probe = $url + '/api/health?launcher_check=' + [guid]::NewGuid().ToString('N')
        $result = Invoke-RestMethod -Uri $probe -Headers @{'Cache-Control'='no-cache'} -TimeoutSec 6 -ErrorAction Stop
        return $result.ok -eq $true
    } catch { return $false }
}
function Publish-TrialUrl([string]$url, [switch]$Verified) {
    if ($url -notmatch '^https://[a-z0-9-]+\.trycloudflare\.com$') { throw 'Invalid public URL.' }
    if (-not $Verified) { throw 'The public HTTPS health check must pass before publishing.' }
    $state['public_url'] = $url
    Save-TrialState
    $url | Set-Content -LiteralPath (Join-Path $trialFolder 'public-url.txt') -Encoding utf8
    $shortcut = "[InternetShortcut]`r`nURL=$url`r`n"
    $shortcut | Set-Content -LiteralPath (Join-Path $PSScriptRoot '打开面试系统.url') -Encoding ascii
    $desktopConfig = Join-Path $trialFolder 'desktop-directory.txt'
    if (Test-Path -LiteralPath $desktopConfig) {
        $desktopFolder = (Get-Content -LiteralPath $desktopConfig -Raw).Trim()
        if (Test-Path -LiteralPath $desktopFolder -PathType Container) {
            $url | Set-Content -LiteralPath (Join-Path $desktopFolder '面试系统-当前网址.txt') -Encoding utf8
            $shortcut | Set-Content -LiteralPath (Join-Path $desktopFolder '打开AI面试系统.url') -Encoding ascii
        }
    }
    $shareConfig = Join-Path $trialFolder 'share-directory.txt'
    if (Test-Path -LiteralPath $shareConfig) {
        $shareFolder = (Get-Content -LiteralPath $shareConfig -Raw).Trim()
        if (Test-Path -LiteralPath $shareFolder -PathType Container) {
            $url | Set-Content -LiteralPath (Join-Path $shareFolder '当前试用网址.txt') -Encoding utf8
            $shortcut | Set-Content -LiteralPath (Join-Path $shareFolder '打开面试系统.url') -Encoding ascii
        }
    }
    Write-TrialStatus '启动成功，当前可以分享的网址：'
    Write-TrialStatus $url
    Write-TrialStatus '请保持电脑开机、联网且不休眠。后台服务会继续运行。'
    if (-not $NoBrowser) {
        try { Start-Process -FilePath $url -ErrorAction Stop }
        catch { Write-TrialStatus '未能自动打开浏览器，请复制上方网址到浏览器访问。' }
    }
}

function Test-TrackedProcess($saved, [string]$kind) {
    if (-not $saved -or -not $saved.ContainsKey($kind + '_pid')) { return $false }
    try {
        $process = Get-Process -Id ([int]$saved[$kind + '_pid']) -ErrorAction Stop
        $expectedStart = [datetime]::Parse($saved[$kind + '_started']).ToUniversalTime()
        return [math]::Abs(($process.StartTime.ToUniversalTime() - $expectedStart).TotalSeconds) -lt 1
    } catch { return $false }
}
function Stop-TrialProcessTree([int]$processId, [datetime]$rootStarted) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$processId" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.CreationDate.ToUniversalTime() -ge $rootStarted.AddSeconds(-1)) {
            Stop-TrialProcessTree ([int]$_.ProcessId) $rootStarted
        }
    }
    Stop-Process -Id $processId -ErrorAction SilentlyContinue
}

Write-TrialStatus '正在检查公网试用服务，请稍候…'
try {
try { $startupHeld = $startupMutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $startupHeld = $true }
if (-not $startupHeld) { throw '另一个启动或停止任务正在运行，请等待原窗口完成。' }
$state = @{}
if (Test-Path -LiteralPath $statePath) {
    # Compatible with both Windows PowerShell 5 and PowerShell 7.
    $object = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $object.PSObject.Properties | ForEach-Object { $state[$_.Name] = $_.Value }
}
if (-not $ReloadApp -and -not $RebuildTunnel -and (Test-TrackedProcess $state 'server') -and (Test-TrackedProcess $state 'tunnel')) {
    $connectedUrl = Read-ConnectedUrl
    if ($connectedUrl) {
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:5010/api/health' -TimeoutSec 3
        } catch { $health = $null }
        if ($health -and $health.ok) {
            Write-TrialStatus '后台服务正在运行，正在实际检查公网是否可访问…'
            if (Test-PublicTrialUrl $connectedUrl) {
                Publish-TrialUrl $connectedUrl -Verified
                exit 0
            }
            Write-TrialStatus '公网检查暂未通过，将保留原连接复查；持续失败时自动重建。'
        }
    }
}
$reuseTunnel = -not $RebuildTunnel -and (Test-TrackedProcess $state 'tunnel')
foreach ($kind in @('tunnel', 'server')) {
    if ($kind -eq 'tunnel' -and $reuseTunnel) { continue }
    if (Test-TrackedProcess $state $kind) {
        Stop-TrialProcessTree ([int]$state[$kind + '_pid']) ([datetime]::Parse($state[$kind + '_started']).ToUniversalTime())
    }
}
if (-not $reuseTunnel) { $state.Remove('public_url') }
Save-TrialState
if (Get-NetTCPConnection -LocalPort 5010 -State Listen -ErrorAction SilentlyContinue) {
    if ($reuseTunnel -and (Test-TrackedProcess $state 'tunnel')) {
        Stop-TrialProcessTree ([int]$state['tunnel_pid']) ([datetime]::Parse($state['tunnel_started']).ToUniversalTime())
        $state.Remove('public_url')
        Save-TrialState
    }
    throw 'Port 5010 is in use by an untracked service. It will not be exposed.'
}
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$tunnelPath = Join-Path $trialFolder 'cloudflared.exe'
if (-not (Test-Path -LiteralPath $tunnelPath)) { throw 'cloudflared.exe is missing; restore the verified tunnel download first.' }
# Keep the previous crash/exit evidence instead of losing it on every redeploy.
$serverGeneration = [guid]::NewGuid().ToString('N')
foreach ($logName in @('server.out.log','server.err.log')) {
    $previousLog = Join-Path $trialFolder $logName
    if (Test-Path -LiteralPath $previousLog) {
        Copy-Item -LiteralPath $previousLog -Destination (Join-Path $trialFolder ($serverGeneration + '.previous.' + $logName))
    }
}
$serverProcess = Start-Process -FilePath $pythonPath -ArgumentList '-u',(Join-Path $PSScriptRoot 'run_public_test.py') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $trialFolder 'server.out.log') -RedirectStandardError (Join-Path $trialFolder 'server.err.log') -PassThru
Write-TrialStatus '正在启动面试服务…'
if (-not $reuseTunnel) { $state = @{} }
$state['server_pid'] = $serverProcess.Id
$state['server_started'] = $serverProcess.StartTime.ToUniversalTime().ToString('o')
Save-TrialState
$originReady = $false
$originDeadline = (Get-Date).AddSeconds(15)
do {
    Start-Sleep -Milliseconds 500
    if ($serverProcess.HasExited) { throw 'The trial server exited during startup.' }
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:5010/api/health' -TimeoutSec 2
        if ($health.ok) { $originReady = $true; break }
    } catch { }
} while ((Get-Date) -lt $originDeadline)
if (-not $originReady) { throw 'Trial server is not ready; no public tunnel was opened.' }
if ($reuseTunnel -and -not $state.ContainsKey('public_url') -and -not $state.ContainsKey('tunnel_log')) {
    Stop-TrialProcessTree ([int]$state['tunnel_pid']) ([datetime]::Parse($state['tunnel_started']).ToUniversalTime())
    $reuseTunnel = $false
}
if ($reuseTunnel) {
    Write-TrialStatus '面试服务已更新，保留原公网隧道和网址，正在检查访问…'
    $tunnelProcess = Get-Process -Id ([int]$state['tunnel_pid']) -ErrorAction Stop
} else {
    Write-TrialStatus '面试服务已就绪，正在连接公网入口（通常需要几秒到一分钟）…'
    $tunnelProcess = Start-NewTrialTunnel
}
Save-TrialState
$deadline = (Get-Date).AddSeconds(60)
$nextPublicCheck = Get-Date
$failedPublicChecks = 0
$rebuiltAfterFailure = $false
do {
    Start-Sleep -Seconds 1
    if ($serverProcess.HasExited) { throw '面试服务已退出，请查看server.err.log；数据已保留。' }
    if ($tunnelProcess.HasExited -and -not $rebuiltAfterFailure) {
        Write-TrialStatus '原隧道已退出，正在重新连接公网入口…'
        $tunnelProcess = Start-NewTrialTunnel
        $rebuiltAfterFailure = $true; $deadline = (Get-Date).AddSeconds(60)
    } elseif ($tunnelProcess.HasExited) { throw '公网隧道启动失败，请查看本次隧道日志。' }
    $connectedUrl = Read-ConnectedUrl
    if ($connectedUrl -and (Get-Date) -ge $nextPublicCheck) {
        Write-TrialStatus '隧道已连接，正在验证真实公网访问…'
        if (Test-PublicTrialUrl $connectedUrl) {
            Publish-TrialUrl $connectedUrl -Verified
            exit 0
        }
        $failedPublicChecks++
        if ($reuseTunnel -and -not $rebuiltAfterFailure -and $failedPublicChecks -ge 3) {
            Write-TrialStatus '原网址连续三次无法访问，正在重建隧道；面试数据和本机服务保留…'
            if (Test-TrackedProcess $state 'tunnel') {
                Stop-TrialProcessTree ([int]$state['tunnel_pid']) ([datetime]::Parse($state['tunnel_started']).ToUniversalTime())
            }
            $tunnelProcess = Start-NewTrialTunnel
            $rebuiltAfterFailure = $true; $failedPublicChecks = 0; $deadline = (Get-Date).AddSeconds(60)
        }
        $nextPublicCheck = (Get-Date).AddSeconds(3)
    }
} while ((Get-Date) -lt $deadline)
throw '公网未能连通。请检查当前网络能否连接 Cloudflare，或换网络后重试。面试数据已保留。'
} catch {
    Write-TrialStatus '启动未完成，请保留此窗口。面试数据没有删除。'
    Write-TrialStatus ('错误详情：' + $_.Exception.Message)
    Write-TrialStatus ('启动日志：' + (Join-Path $trialFolder 'startup.log'))
    exit 1
}
finally {
    if ($startupHeld) { $startupMutex.ReleaseMutex() }
    $startupMutex.Dispose()
}
