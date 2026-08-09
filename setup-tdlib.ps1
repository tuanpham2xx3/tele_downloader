[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$runtime = Join-Path $root ".runtime"
$install = Join-Path $runtime "tdlib"
$source = Join-Path $install "source"
$jdk = Join-Path $install "jdk"
$lib = Join-Path $install "lib"
$jar = Join-Path $install "telegram-files.jar"
$envFile = Join-Path $runtime "tdlib.env"
$jdkArchive = Join-Path $runtime "zulu-jdk23-windows.zip"
$libsArchive = Join-Path $runtime "tdlib-libs-1.15.0.zip"

New-Item -ItemType Directory -Path $runtime,$install,$lib -Force | Out-Null

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required. Install Git for Windows first."
}

if (-not (Test-Path -LiteralPath (Join-Path $source ".git"))) {
    git clone --depth 1 --branch 0.1.15 https://github.com/jarvis2f/telegram-files.git $source
    if ($LASTEXITCODE -ne 0) { throw "Failed to clone telegram-files 0.1.15." }
}

if (-not (Test-Path -LiteralPath (Join-Path $jdk "bin\java.exe"))) {
    if (-not (Test-Path -LiteralPath $jdkArchive)) {
        Invoke-WebRequest -Uri "https://cdn.azul.com/zulu/bin/zulu23.32.11-ca-jdk23.0.2-win_x64.zip" -OutFile $jdkArchive
    }
    $extract = Join-Path $runtime "jdk23-extract"
    Remove-Item -LiteralPath $extract -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -LiteralPath $jdkArchive -DestinationPath $extract -Force
    $top = Get-ChildItem -LiteralPath $extract -Directory | Select-Object -First 1
    if (-not $top) { throw "JDK archive has no root directory." }
    Remove-Item -LiteralPath $jdk -Recurse -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $top.FullName -Destination $jdk
    Remove-Item -LiteralPath $extract -Recurse -Force
}

if (-not (Test-Path -LiteralPath (Join-Path $lib "tdjni.dll"))) {
    if (-not (Test-Path -LiteralPath $libsArchive)) {
        Invoke-WebRequest -Uri "https://github.com/p-vorobyev/spring-boot-starter-telegram/releases/download/1.15.0/libs.zip" -OutFile $libsArchive
    }
    $extract = Join-Path $runtime "tdlib-libs-extract"
    Remove-Item -LiteralPath $extract -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -LiteralPath $libsArchive -DestinationPath $extract -Force
    $windowsLib = Get-ChildItem -LiteralPath $extract -Recurse -Directory |
        Where-Object Name -eq "windows_x64" | Select-Object -First 1
    if (-not $windowsLib) { throw "windows_x64 TDLib directory was not found." }
    Copy-Item -Path (Join-Path $windowsLib.FullName "*") -Destination $lib -Force
    Remove-Item -LiteralPath $extract -Recurse -Force
}

if (-not (Test-Path -LiteralPath $jar)) {
    $oldJavaHome = $env:JAVA_HOME
    $oldPath = $env:PATH
    try {
        $env:JAVA_HOME = $jdk
        $env:PATH = "$(Join-Path $jdk 'bin');$env:PATH"
        & (Join-Path $source "api\gradlew.bat") -p (Join-Path $source "api") shadowJar
        if ($LASTEXITCODE -ne 0) { throw "Gradle build failed." }
        Copy-Item -LiteralPath (Join-Path $source "api\build\libs\telegram-files.jar") -Destination $jar -Force
    }
    finally {
        $env:JAVA_HOME = $oldJavaHome
        $env:PATH = $oldPath
    }
}

if (-not (Test-Path -LiteralPath $envFile)) {
    $workflow = Get-Content -LiteralPath (Join-Path $source ".github\workflows\ci.yml") -Raw
    $id = [regex]::Match($workflow, '(?m)^\s*TELEGRAM_API_ID=(\d+)\s*$')
    $hash = [regex]::Match($workflow, '(?m)^\s*TELEGRAM_API_HASH=([0-9a-fA-F]+)\s*$')
    if (-not $id.Success -or -not $hash.Success) {
        throw "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in $envFile."
    }
    @(
        "TELEGRAM_API_ID=$($id.Groups[1].Value)"
        "TELEGRAM_API_HASH=$($hash.Groups[1].Value)"
        "TDLIB_JAVA=$(Join-Path $jdk 'bin\java.exe')"
        "TDLIB_JAR_PATH=$jar"
        "TDLIB_LIBRARY_PATH=$lib"
        "TDLIB_DATA_ROOT=$(Join-Path $install 'data')"
    ) | Set-Content -LiteralPath $envFile -Encoding utf8
}

& (Join-Path $jdk "bin\java.exe") -version
Write-Host "TDLib backend artifacts are ready in $install" -ForegroundColor Green
Write-Host "Start: .\.venv\Scripts\python.exe tdlib_backend.py start" -ForegroundColor Cyan
