[CmdletBinding()]
param()

& (Join-Path $PSScriptRoot "start-multi-pipeline.ps1") -Action Start
exit $LASTEXITCODE
