[CmdletBinding()]
param(
    [switch]$SkipTelegram
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$credentialPath = Join-Path $projectRoot ".telerecon-credentials.xml"
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$bootstrapPath = Join-Path $projectRoot "telerecon_bootstrap.py"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Chưa cài dependency. Chạy .\install-telerecon.ps1 trước."
}

if (-not (Test-Path -LiteralPath $credentialPath)) {
    throw "Chưa cấu hình Telegram API. Chạy .\configure-telerecon.ps1 trước."
}

if (-not $SkipTelegram) {
    & (Join-Path $projectRoot "start-chrome-telegram.ps1")
}

$credentials = Import-Clixml -LiteralPath $credentialPath

try {
    $env:TELERECON_API_ID = [System.Net.NetworkCredential]::new("", $credentials.ApiId).Password
    $env:TELERECON_API_HASH = [System.Net.NetworkCredential]::new("", $credentials.ApiHash).Password
    $env:TELERECON_PHONE = [System.Net.NetworkCredential]::new("", $credentials.Phone).Password
    & $pythonPath $bootstrapPath
}
finally {
    Remove-Item Env:\TELERECON_API_ID -ErrorAction SilentlyContinue
    Remove-Item Env:\TELERECON_API_HASH -ErrorAction SilentlyContinue
    Remove-Item Env:\TELERECON_PHONE -ErrorAction SilentlyContinue
}
