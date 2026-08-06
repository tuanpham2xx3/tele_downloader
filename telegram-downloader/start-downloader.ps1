[CmdletBinding()]
param(
    [string]$InputFile,
    [string]$TargetChat = "@coursebusters_bot",
    [string]$OutputDir = "..\downloads"
)

$ErrorActionPreference = "Stop"

$downloaderDir = $PSScriptRoot
$projectRoot = Split-Path -Path $downloaderDir -Parent

$credentialPath = Join-Path $projectRoot ".telerecon-credentials.xml"
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$downloaderScript = Join-Path $downloaderDir "downloader.py"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Chưa tìm thấy môi trường Python ảo (.venv). Hãy chạy .\install-telerecon.ps1 trước."
}

if (-not (Test-Path -LiteralPath $credentialPath)) {
    throw "Chưa cấu hình Telegram API Credentials. Hãy chạy .\configure-telerecon.ps1 trước."
}

$credentials = Import-Clixml -LiteralPath $credentialPath

try {
    $env:TELERECON_API_ID = [System.Net.NetworkCredential]::new("", $credentials.ApiId).Password
    $env:TELERECON_API_HASH = [System.Net.NetworkCredential]::new("", $credentials.ApiHash).Password
    $env:TELERECON_PHONE = [System.Net.NetworkCredential]::new("", $credentials.Phone).Password

    $pythonArgs = @($downloaderScript, "-c", $TargetChat, "-o", $OutputDir)
    if ($InputFile) {
        $pythonArgs += @("-i", $InputFile)
    }

    Write-Host "🚀 Đang khởi động Telegram Auto File Downloader..." -ForegroundColor Cyan
    & $pythonPath $pythonArgs
}
finally {
    Remove-Item Env:\TELERECON_API_ID -ErrorAction SilentlyContinue
    Remove-Item Env:\TELERECON_API_HASH -ErrorAction SilentlyContinue
    Remove-Item Env:\TELERECON_PHONE -ErrorAction SilentlyContinue
}
