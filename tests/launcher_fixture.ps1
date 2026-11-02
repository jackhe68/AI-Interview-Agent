param([string]$Project,[string]$Scenario)
$ErrorActionPreference='Stop'
$global:TrialFixtureClock=0
$global:TrialFixtureBase=[datetime]::UtcNow
$global:TrialFixtureCalls=New-Object System.Collections.ArrayList
$global:TrialTunnelStarts=0
$global:TrialLocalChecks=0
if($Scenario -eq 'cold-http'){
    Add-Type -TypeDefinition 'public class TrialFixtureHttpResponse : System.Net.WebResponse { public System.Net.HttpStatusCode StatusCode { get { return System.Net.HttpStatusCode.BadGateway; } } }'
}
function Record-Call($kind,$value) {
    [void]$global:TrialFixtureCalls.Add(@{kind=$kind;value=$value;seconds=$global:TrialFixtureClock})
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
    if($Uri -like 'http://127.0.0.1:*'){
        $global:TrialLocalChecks++
        if($Scenario -eq 'cold-origin-fails' -and $global:TrialLocalChecks -gt 1){throw 'Fixture origin stopped'}
        return @{ok=$true}
    }
    if($Uri -like 'https://saved-current.trycloudflare.com/*'){
        if($Scenario -in @('recover','recover-no-reload')){throw 'Simulated disconnected old tunnel'}
        return @{ok=$true}
    }
    if($Uri -like 'https://fresh-current.trycloudflare.com/*' -or $Uri -like 'https://replacement-current.trycloudflare.com/*'){
        if($Scenario -eq 'cold-html'){return '<html>not a health response</html>'}
        if($Scenario -eq 'cold-http'){throw (New-Object Net.WebException('fixture secret must not be logged',$null,[Net.WebExceptionStatus]::ProtocolError,(New-Object TrialFixtureHttpResponse)))}
        if($Scenario -eq 'cold-tls'){throw (New-Object Net.WebException('fixture secret must not be logged',[Net.WebExceptionStatus]::TrustFailure))}
        if($Scenario -eq 'cold-timeout'){throw (New-Object Net.WebException('fixture secret must not be logged',[Net.WebExceptionStatus]::Timeout))}
        if(($Scenario -eq 'cold-delayed' -and $global:TrialFixtureClock -lt 90) -or
           ($Scenario -in @('cold-rebuild','cold-origin-fails') -and $global:TrialTunnelStarts -eq 1)){
            throw (New-Object Net.WebException('fixture secret must not be logged',[Net.WebExceptionStatus]::NameResolutionFailure))
        }
        return @{ok=$true}
    }
    throw 'Unexpected stale-log address'
}
function Start-Process { param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,$RedirectStandardOutput,$RedirectStandardError,[switch]$PassThru)
    if($FilePath -like '*cloudflared.exe'){
        $global:TrialTunnelStarts++
        Record-Call 'start-tunnel' $RedirectStandardError
        $url = if($global:TrialTunnelStarts -eq 1){'https://fresh-current.trycloudflare.com'}else{'https://replacement-current.trycloudflare.com'}
        $message = if($Scenario -eq 'cold-unregistered'){$url}else{"$url`nRegistered tunnel connection"}
        $message | Set-Content -LiteralPath $RedirectStandardError
        return [pscustomobject]@{Id=2002;StartTime=$global:TrialFixtureBase;HasExited=$false}
    }
    Record-Call 'start-server' $FilePath
    return [pscustomobject]@{Id=2001;StartTime=$global:TrialFixtureBase;HasExited=$false}
}
$runtime=Join-Path $Project '.public-test'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
'fixture binary - never executed' | Set-Content -LiteralPath (Join-Path $runtime 'cloudflared.exe')
"https://wrong-shared.trycloudflare.com`nRegistered tunnel connection" | Set-Content -LiteralPath (Join-Path $runtime 'tunnel.err.log')
$initialState = if($Scenario -like 'cold-*'){@{}}else{@{server_pid=1001;server_started=$global:TrialFixtureBase.ToString('o');tunnel_pid=1002;tunnel_started=$global:TrialFixtureBase.ToString('o');public_url='https://saved-current.trycloudflare.com'}}
$initialState | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'processes.json') -Encoding utf8
$script=Join-Path $Project 'tools/start_public_test.ps1'
if($Scenario -eq 'stop') { & (Join-Path $Project 'tools/stop_public_test.ps1') }
elseif($Scenario -in @('healthy','recover-no-reload')) { & $script -NoBrowser }
else { & $script -NoBrowser -ReloadApp }
exit $LASTEXITCODE
