$vpsHost = "019fe046-2e97-7ba9-9e28-cf3b378e3148.gitpod.environment"

function Get-Base64File($path) {
    $fs = New-Object System.IO.FileStream($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    $buf = New-Object byte[] $fs.Length
    [void]$fs.Read($buf, 0, $fs.Length)
    $fs.Close()
    return [System.Convert]::ToBase64String($buf)
}

$s1 = Get-Base64File "c:\PROJECT\_EXTENTSION\_GETURL\telegram_media_downloader\pyrogram.session"
$s2 = Get-Base64File "c:\PROJECT\_EXTENTSION\_GETURL\telegram_media_downloader\pyrogram_acc2.session"
$s3 = Get-Base64File "c:\PROJECT\_EXTENTSION\_GETURL\telegram_media_downloader\pyrogram_acc3.session"

Write-Host "[INFO] Đang tạo thư mục ~/.telegram_sessions trên VPS ONA mới..."
ssh -o StrictHostKeyChecking=no $vpsHost "mkdir -p ~/.telegram_sessions"

Write-Host "[INFO] Uploading pyrogram.session (Acc 1 Master)..."
$s1 | ssh -o StrictHostKeyChecking=no $vpsHost "base64 -d > ~/.telegram_sessions/pyrogram.session"

Write-Host "[INFO] Uploading pyrogram_acc2.session (Acc 2 Relay)..."
$s2 | ssh -o StrictHostKeyChecking=no $vpsHost "base64 -d > ~/.telegram_sessions/pyrogram_acc2.session"

Write-Host "[INFO] Uploading pyrogram_acc3.session (Acc 3 Relay)..."
$s3 | ssh -o StrictHostKeyChecking=no $vpsHost "base64 -d > ~/.telegram_sessions/pyrogram_acc3.session"

Write-Host "[SUCCESS] Kiểm tra danh sách file session trên VPS ONA mới:"
ssh -o StrictHostKeyChecking=no $vpsHost "ls -lh ~/.telegram_sessions/"
