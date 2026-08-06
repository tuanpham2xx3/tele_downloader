[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$repoPath = Join-Path $projectRoot "Telerecon"
$venvPath = Join-Path $projectRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path -LiteralPath (Join-Path $repoPath "requirements.txt"))) {
    throw "Không tìm thấy Telerecon. Chạy 'git submodule update --init' trước."
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv $venvPath
}

& $pythonPath -m pip install --upgrade pip

# 'datetime' is part of Python's standard library. The similarly named PyPI
# package is obsolete and is intentionally excluded from the upstream list.
$requirements = Get-Content -LiteralPath (Join-Path $repoPath "requirements.txt") |
    Where-Object { $_.Trim() -and $_.Trim().ToLowerInvariant() -ne "datetime" }
$temporaryRequirements = Join-Path $env:TEMP "telerecon-requirements-$PID.txt"

try {
    Set-Content -LiteralPath $temporaryRequirements -Value $requirements -Encoding utf8
    & $pythonPath -m pip install -r $temporaryRequirements
    if ($LASTEXITCODE -ne 0) {
        throw "Cài dependency Telerecon thất bại."
    }
}
finally {
    Remove-Item -LiteralPath $temporaryRequirements -Force -ErrorAction SilentlyContinue
}

Write-Host "Đã cài Telerecon trong môi trường: $venvPath"
