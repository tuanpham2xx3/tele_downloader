[CmdletBinding()]
param(
    [string]$Url = "https://web.telegram.org/k/"
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$profilePath = Join-Path $projectRoot "Chrome_Telegram_Profile"
$extensionPath = Join-Path $projectRoot "telegram-link-collector"
$chromeCandidates = @(
    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
)
$chromePath = $chromeCandidates |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
    Select-Object -First 1

if (-not $chromePath) {
    throw "Không tìm thấy Google Chrome trên máy."
}

if (-not (Test-Path -LiteralPath $profilePath)) {
    New-Item -ItemType Directory -Path $profilePath | Out-Null
}

$chromeArguments = @(
    "--user-data-dir=$profilePath",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-sync",
    $Url
)

if (Test-Path -LiteralPath (Join-Path $extensionPath "manifest.json")) {
    $chromeArguments = @("--load-extension=$extensionPath") + $chromeArguments
}

Write-Host "Mở Telegram bằng profile riêng: $profilePath"
Start-Process -FilePath $chromePath -ArgumentList $chromeArguments -WindowStyle Normal
