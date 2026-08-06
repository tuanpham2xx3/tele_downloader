[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$credentialPath = Join-Path $PSScriptRoot ".telerecon-credentials.xml"
$apiId = Read-Host "Telegram API ID" -AsSecureString
$apiHash = Read-Host "Telegram API Hash" -AsSecureString
$phone = Read-Host "Số điện thoại Telegram (định dạng quốc tế, ví dụ +84...)" -AsSecureString

[pscustomobject]@{
    ApiId = $apiId
    ApiHash = $apiHash
    Phone = $phone
} | Export-Clixml -LiteralPath $credentialPath

Write-Host "Đã lưu credential được Windows mã hóa cho đúng user hiện tại."
Write-Host "File này không được Git theo dõi: $credentialPath"
