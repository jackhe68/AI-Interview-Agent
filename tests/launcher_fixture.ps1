param([string]$Project,[string]$Scenario)
$ErrorActionPreference='Stop'
$global:TrialFixtureClock=0
$global:TrialFixtureBase=[datetime]::UtcNow
$global:TrialFixtureCalls=New-Object System.Collections.ArrayList
function Record-Call($kind,$value) {
    [void]$global:TrialFixtureCalls.Add(@{kind=$kind;value=$value})
    ConvertTo-Json -InputObject @($global:TrialFixtureCalls.ToArray()) | Set-Content -LiteralPath (Join-Path $Project 'calls.json') -Encoding utf8
}
function Get-Date { param($Format)
    $date=$global:TrialFixtureBase.AddSeconds($global:TrialFixtureClock)
    if($Format){return $date.ToString($Format)}
    return $date
}
function Start-Sleep { param($Seconds,$Milliseconds) $global:TrialFixtureClock+=[double]$Seconds+[double]$Milliseconds/1000 }
function Get-Process { param($Id,$ErrorAction)
    return [pscustomobject]@{Id=$Id;StartTime=$global:TrialFixtureBase;HasExited=$false}
}
function Get-CimInstance { param($ClassName,$Filter,$ErrorAction) return @() }
function Stop-Process { param($Id,$ErrorAction) Record-Call 'stop' $Id }
function Get-NetTCPConnection { param($LocalPort,$State,$ErrorAction)
    if($Scenario -eq 'blocked-port'){return [pscustomobject]@{State='Listen';OwningProcess=9999}}
}
function Invoke-RestMethod { param($Uri,$Headers,$TimeoutSec,$ErrorAction)
    Record-Call 'probe' $Uri
    if($Uri -like 'http://127.0.0.1:*'){return @{ok=$true}}
    if($Uri -like 'https://saved-current.trycloudflare.com/*'){
        if($Scenario -eq 'recover'){throw 'Simulated disconnected old tunnel'}
        return @{ok=$true}
    }
    if($Uri -like 'https://fresh-current.trycloudflare.com/*'){return @{ok=$true}}
    throw 'Unexpected stale-log address'
}
function Start-Process { param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,$RedirectStandardOutput,$RedirectStandardError,[switch]$PassThru)
    if($FilePath -like '*cloudflared.exe'){
        Record-Call 'start-tunnel' $RedirectStandardError
        "https://fresh-current.trycloudflare.com`nRegistered tunnel connection" | Set-Content -LiteralPath $RedirectStandardError
        return [pscustomobject]@{Id=2002;StartTime=$global:TrialFixtureBase;HasExited=$false}
    }
    Record-Call 'start-server' $FilePath
    return [pscustomobject]@{Id=2001;StartTime=$global:TrialFixtureBase;HasExited=$false}
}
$runtime=Join-Path $Project '.public-test'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
'fixture binary - never executed' | Set-Content -LiteralPath (Join-Path $runtime 'cloudflared.exe')
"https://wrong-shared.trycloudflare.com`nRegistered tunnel connection" | Set-Content -LiteralPath (Join-Path $runtime 'tunnel.err.log')
@{server_pid=1001;server_started=$global:TrialFixtureBase.ToString('o');tunnel_pid=1002;tunnel_started=$global:TrialFixtureBase.ToString('o');public_url='https://saved-current.trycloudflare.com'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'processes.json') -Encoding utf8
$script=Join-Path $Project 'tools/start_public_test.ps1'
if($Scenario -eq 'stop') { & (Join-Path $Project 'tools/stop_public_test.ps1') }
elseif($Scenario -eq 'healthy') { & $script -NoBrowser }
else { & $script -NoBrowser -ReloadApp }
exit $LASTEXITCODE
