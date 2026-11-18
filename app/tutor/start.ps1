param(
    [string]$Unit = ''
)
$ErrorActionPreference = 'Stop'
$appDirectory = $PSScriptRoot
$serverFile = Join-Path $appDirectory 'server.py'
$localUrl = 'http://127.0.0.1:8766'
$pythonExe = (Get-Command python -ErrorAction Stop).Source
$ready = $false
try { $r = Invoke-RestMethod ($localUrl + '/api/units') -TimeoutSec 2; $ready = $r.Length -gt 0 } catch {}
if (-not $ready) {
    $stdoutPath = Join-Path $appDirectory 'runtime-out.log'
    $stderrPath = Join-Path $appDirectory 'runtime-error.log'
    Start-Process -FilePath $pythonExe -ArgumentList @('-u', ('"' + $serverFile + '"')) -WorkingDirectory $appDirectory -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    for ($i=0; $i -lt 25; $i++) {
        Start-Sleep -Milliseconds 400
        try { $r = Invoke-RestMethod ($localUrl + '/api/units') -TimeoutSec 1; if ($r.Length -gt 0) { $ready=$true; break } } catch {}
    }
}
if (-not $ready) { throw 'Could not start the local lesson. See runtime-error.log in this folder.' }
$targetUrl = if ($Unit) { "$localUrl`?unit=$Unit" } else { $localUrl }
Start-Process $targetUrl
