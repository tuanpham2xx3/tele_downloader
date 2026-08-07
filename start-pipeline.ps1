[CmdletBinding()]
param(
    [string]$RcloneDest = "gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:",
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$credentialPath = Join-Path $projectRoot ".telerecon-credentials.xml"
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pipelineScript = Join-Path $projectRoot "telegram_media_downloader\course_pipeline.py"

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

    Write-Host "🚀 Launching Telegram Course Pipeline Automator..." -ForegroundColor Cyan
    Write-Host "📊 Web Log Monitor available at: http://localhost:$Port" -ForegroundColor Green

    & $pythonPath $pipelineScript -r $RcloneDest -p $Port
}
finally {
    Remove-Item Env:\TELERECON_API_ID -ErrorAction SilentlyContinue
    Remove-Item Env:\TELERECON_API_HASH -ErrorAction SilentlyContinue
    Remove-Item Env:\TELERECON_PHONE -ErrorAction SilentlyContinue
}
