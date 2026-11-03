param([string]$Project,[string]$TestPython,[string]$Scenario)
$ErrorActionPreference='Stop'
$global:UploadFixtureCalls=New-Object System.Collections.ArrayList
function Record-Call($kind) {
    [void]$global:UploadFixtureCalls.Add($kind)
    ConvertTo-Json -InputObject @($global:UploadFixtureCalls.ToArray()) | Set-Content -LiteralPath (Join-Path $Project 'calls.json') -Encoding utf8
}
function python {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    $kind=if($Arguments -contains '--verify'){'verify'}else{'package'}
    Record-Call $kind
    if($Scenario -eq ($kind+'-fail')) { $global:LASTEXITCODE=7;return }
    if($Scenario -eq 'no-archive' -and $kind -eq 'package') { $global:LASTEXITCODE=0;return }
    & $TestPython @Arguments
}
function scp {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    Record-Call 'scp'
    $global:LASTEXITCODE=if($Scenario -eq 'scp-fail'){8}else{0}
}
function ssh {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    Record-Call 'ssh'
    $command=$Arguments[-1]
    if($command -match 'chown|chmod|restart|bootstrap') {throw 'Unexpected runtime mutation'}
    $global:LASTEXITCODE=if($Scenario -eq 'ssh-fail'){9}else{0}
}
$script=Join-Path $Project 'deploy\upload.ps1'
if($Scenario -eq 'local-only') { & $script -PackageOnly }
elseif($Scenario -eq 'invalid-target') { & $script -Server 'fictional.invalid' -RemoteDir '/var/www/../private' }
else { & $script -Server 'fictional.invalid' }
exit $LASTEXITCODE
