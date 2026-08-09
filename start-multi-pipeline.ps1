[CmdletBinding()]
param(
    [ValidateSet("Start", "Status", "Stop")]
    [string]$Action = "Start",
    [string]$RcloneDest = "gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:",
    [long]$RelayGroupAcc2 = -5040203514,
    [long]$RelayGroupAcc3 = -5281140814
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pipelineScript = Join-Path $projectRoot "telegram_media_downloader\course_pipeline.py"
$relayScript = Join-Path $projectRoot "telegram_media_downloader\relay_pipeline.py"
$processorScript = Join-Path $projectRoot "telegram_media_downloader\processing_worker.py"
$uploaderScript = Join-Path $projectRoot "telegram_media_downloader\drive_uploader.py"
$recoveryScript = Join-Path $projectRoot "telegram_media_downloader\recover_pipeline_state.py"
$monitorScript = Join-Path $projectRoot "monitor_windows.py"
$backendManager = Join-Path $projectRoot "tdlib_backend.py"
$runtimeDir = Join-Path $projectRoot ".runtime"
$statePath = Join-Path $runtimeDir "pipeline-state.json"
$legacyStatePath = Join-Path $runtimeDir "windows-pipelines.json"
$accountRegistry = Join-Path $runtimeDir "tdlib-accounts.json"
$credentialPath = Join-Path $projectRoot ".telerecon-credentials.xml"

$definitions = @(
    [pscustomobject]@{ Name = "acc1"; Script = $pipelineScript; Port = 5000; Log = "pipeline_acc1" },
    [pscustomobject]@{ Name = "acc2"; Script = $relayScript; Port = 5001; Log = "pipeline_acc2" },
    [pscustomobject]@{ Name = "acc3"; Script = $relayScript; Port = 5002; Log = "pipeline_acc3" }
    [pscustomobject]@{ Name = "processor"; Script = $processorScript; Port = 0; Log = "processor" }
    [pscustomobject]@{ Name = "uploader"; Script = $uploaderScript; Port = 0; Log = "uploader" }
)

function Get-SavedState {
    $sourcePath = if (Test-Path -LiteralPath $statePath) { $statePath } elseif (Test-Path -LiteralPath $legacyStatePath) { $legacyStatePath } else { $null }
    if (-not $sourcePath) { return @() }
    try {
        return @(Get-Content -Raw -LiteralPath $sourcePath | ConvertFrom-Json)
    }
    catch {
        Write-Warning "State file is invalid; treating it as empty: $sourcePath"
        return @()
    }
}

function Get-ManagedProcess([object]$Entry) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($Entry.Pid)" -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    if ($process.CommandLine -notlike "*$($Entry.Script)*") { return $null }
    return $process
}

function Show-Status {
    & $pythonPath $backendManager status
    $saved = Get-SavedState
    $rows = foreach ($definition in $definitions) {
        $entry = $saved | Where-Object Name -eq $definition.Name | Select-Object -First 1
        $process = if ($entry) { Get-ManagedProcess $entry } else { $null }
        $listener = if ($definition.Port -gt 0) {
            Get-NetTCPConnection -State Listen -LocalPort $definition.Port -ErrorAction SilentlyContinue |
                Select-Object -First 1
        } else { $null }
        [pscustomobject]@{
            Account = $definition.Name
            Running = [bool]$process
            PID = if ($process) { $process.ProcessId } else { "-" }
            Port = $definition.Port
            Listening = [bool]$listener
        }
    }
    $rows | Format-Table -AutoSize
}

function Stop-ProcessTree([int]$RootPid) {
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $children = @($all | Where-Object ParentProcessId -eq $RootPid)
    foreach ($child in $children) {
        Stop-ProcessTree -RootPid $child.ProcessId
    }
    Stop-Process -Id $RootPid -Force -ErrorAction SilentlyContinue
}

function Stop-Pipelines {
    $saved = Get-SavedState
    foreach ($entry in $saved) {
        $process = Get-ManagedProcess $entry
        if ($process) {
            Write-Host "Stopping $($entry.Name) (PID=$($entry.Pid))..." -ForegroundColor Yellow
            Stop-ProcessTree -RootPid $entry.Pid
        }
    }
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $legacyStatePath -Force -ErrorAction SilentlyContinue
    & $pythonPath $backendManager stop
    Write-Host "Native Windows pipelines stopped." -ForegroundColor Green
}

if ($Action -eq "Status") {
    Show-Status
    exit 0
}

if ($Action -eq "Stop") {
    Stop-Pipelines
    exit 0
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python virtual environment not found: $pythonPath"
}

foreach ($requiredFile in @($pipelineScript, $relayScript, $processorScript, $uploaderScript, $recoveryScript, $monitorScript, $backendManager)) {
    if (-not (Test-Path -LiteralPath $requiredFile)) {
        throw "Required script not found: $requiredFile"
    }
}

$active = @(Get-SavedState | Where-Object { Get-ManagedProcess $_ })
if ($active.Count -gt 0) {
    throw "One or more managed pipelines are already running. Use -Action Status or -Action Stop first."
}

& $pythonPath $backendManager start
if ($LASTEXITCODE -ne 0) {
    throw "TDLib backend failed to start. Run .\setup-tdlib.ps1 first."
}

if (-not (Test-Path -LiteralPath $accountRegistry)) {
    throw "TDLib account registry not found. Run: $pythonPath tdlib_admin.py login acc1"
}
$registry = Get-Content -LiteralPath $accountRegistry -Raw | ConvertFrom-Json
foreach ($role in @("acc1", "acc2", "acc3")) {
    if (-not $registry.$role.id) {
        throw "TDLib account $role is not configured. Run: $pythonPath tdlib_admin.py login $role"
    }
}

foreach ($port in 5000..5003) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use."
    }
}

& $pythonPath $recoveryScript
if ($LASTEXITCODE -ne 0) {
    throw "Failed to recover transient pipeline claims."
}

if (-not (Get-Command rclone -ErrorAction SilentlyContinue)) {
    throw "rclone is not available in PATH."
}

$sevenZip = Get-Command 7z -ErrorAction SilentlyContinue
if (-not $sevenZip) {
    $sevenZipPath = Join-Path $env:ProgramFiles "7-Zip\7z.exe"
    if (Test-Path -LiteralPath $sevenZipPath) {
        $env:PATH = "$(Split-Path $sevenZipPath);$env:PATH"
    }
    else {
        throw "7-Zip is required. Install it with: winget install --id 7zip.7zip -e"
    }
}

& $pythonPath -c "import rich, requests, websockets" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Python dependencies are incomplete. Required modules: rich, requests, websockets."
}

$oldApiId = $env:TELERECON_API_ID
$oldApiHash = $env:TELERECON_API_HASH
$oldPhone = $env:TELERECON_PHONE
$oldPythonUtf8 = $env:PYTHONUTF8
$oldPythonIoEncoding = $env:PYTHONIOENCODING
$started = @()

try {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    if (Test-Path -LiteralPath $credentialPath) {
        $credentials = Import-Clixml -LiteralPath $credentialPath
        $env:TELERECON_API_ID = [System.Net.NetworkCredential]::new("", $credentials.ApiId).Password
        $env:TELERECON_API_HASH = [System.Net.NetworkCredential]::new("", $credentials.ApiHash).Password
        $env:TELERECON_PHONE = [System.Net.NetworkCredential]::new("", $credentials.Phone).Password
    }

    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

    $launches = @(
        [pscustomobject]@{
            Definition = $definitions[0]
            Arguments = @("-u", $pipelineScript, "-r", $RcloneDest, "-p", "5000", "--relay-acc2", "$RelayGroupAcc2", "--relay-acc3", "$RelayGroupAcc3")
        },
        [pscustomobject]@{
            Definition = $definitions[1]
            Arguments = @("-u", $relayScript, "--session", "pyrogram_acc2", "--group", "$RelayGroupAcc2", "--rclone-dest", $RcloneDest, "--port", "5001")
        },
        [pscustomobject]@{
            Definition = $definitions[2]
            Arguments = @("-u", $relayScript, "--session", "pyrogram_acc3", "--group", "$RelayGroupAcc3", "--rclone-dest", $RcloneDest, "--port", "5002")
        },
        [pscustomobject]@{
            Definition = $definitions[3]
            Arguments = @("-u", $processorScript)
        },
        [pscustomobject]@{
            Definition = $definitions[4]
            Arguments = @("-u", $uploaderScript)
        },
        [pscustomobject]@{
            Definition = [pscustomobject]@{ Name = "monitor"; Script = $monitorScript; Port = 0; Log = "windows_monitor" }
            Arguments = @("-u", $monitorScript)
        }
    )

    foreach ($launch in $launches) {
        if ($launch.Definition.Name -in @("acc2", "acc3")) {
            $stdout = Join-Path $projectRoot "$($launch.Definition.Log).log"
        }
        else {
            $stdout = Join-Path $runtimeDir "$($launch.Definition.Log).stdout.log"
        }
        $stderr = Join-Path $runtimeDir "$($launch.Definition.Log).stderr.log"
        $process = Start-Process -FilePath $pythonPath -ArgumentList $launch.Arguments `
            -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $started += [pscustomobject]@{
            Name = $launch.Definition.Name
            Pid = $process.Id
            Script = $launch.Definition.Script
            Port = $launch.Definition.Port
            StartedAt = (Get-Date).ToString("o")
        }
        Start-Sleep -Seconds 1
    }

    $started | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
    Start-Sleep -Seconds 5

    $dead = @($started | Where-Object { -not (Get-ManagedProcess $_) })
    if ($dead.Count -gt 0) {
        throw "Pipeline startup failed: $($dead.Name -join ', '). Check .runtime/*.stderr.log"
    }

    Write-Host "Three TDLib accounts are running natively on Windows." -ForegroundColor Green
    Write-Host "Dashboard: http://localhost:5000" -ForegroundColor Cyan
    Show-Status
}
catch {
    foreach ($entry in $started) {
        if (Get-ManagedProcess $entry) {
            Stop-ProcessTree -RootPid $entry.Pid
        }
    }
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    throw
}
finally {
    $env:TELERECON_API_ID = $oldApiId
    $env:TELERECON_API_HASH = $oldApiHash
    $env:TELERECON_PHONE = $oldPhone
    $env:PYTHONUTF8 = $oldPythonUtf8
    $env:PYTHONIOENCODING = $oldPythonIoEncoding
}
