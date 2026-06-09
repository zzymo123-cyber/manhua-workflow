$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RootDir

$Port = if ($env:MANHUA_PORT) { $env:MANHUA_PORT } elseif ($env:PORT) { $env:PORT } else { "8002" }

$ParsedPort = 0
if (-not [int]::TryParse($Port, [ref]$ParsedPort) -or $ParsedPort -lt 1 -or $ParsedPort -gt 65535) {
  Write-Error "MANHUA_PORT/PORT must be an integer between 1 and 65535."
  exit 2
}
$Port = [string]$ParsedPort

if (-not (Test-Path ".venv")) {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m venv .venv
  } else {
    python -m venv .venv
  }
}

$Python = Join-Path $RootDir ".venv\Scripts\python.exe"
& $Python -m pip install -r requirements.txt

$env:MANHUA_PORT = $Port
$Url = "http://localhost:$Port"
$HealthUrl = "$Url/api/health"
Start-Job -ScriptBlock {
  param($HealthUrl, $Url)
  for ($i = 0; $i -lt 60; $i++) {
    try {
      Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 1 | Out-Null
      Start-Process $Url
      return
    } catch {
      Start-Sleep -Seconds 1
    }
  }
} -ArgumentList $HealthUrl, $Url | Out-Null
& $Python main.py
