$vpsHost = "019fe046-2e97-7ba9-9e28-cf3b378e3148.gitpod.environment"
$rclonePath = "$env:USERPROFILE\AppData\Roaming\rclone\rclone.conf"

if (!(Test-Path $rclonePath)) {
    Write-Host "[ERROR] Không tìm thấy file rclone.conf tại: $rclonePath"
    exit 1
}

$fs = New-Object System.IO.FileStream($rclonePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
$buf = New-Object byte[] $fs.Length
[void]$fs.Read($buf, 0, $fs.Length)
$fs.Close()
$b64 = [System.Convert]::ToBase64String($buf)

Write-Host "[INFO] Đang tạo thư mục ~/.config/rclone trên VPS ONA mới..."
ssh -o StrictHostKeyChecking=no $vpsHost "mkdir -p ~/.config/rclone"

Write-Host "[INFO] Uploading rclone.conf..."
$b64 | ssh -o StrictHostKeyChecking=no $vpsHost "base64 -d > ~/.config/rclone/rclone.conf"

Write-Host "[SUCCESS] Thử quét trực tiếp danh sách thư mục Google Drive qua Rclone trên VPS:"
ssh -o StrictHostKeyChecking=no $vpsHost "rclone lsf 'gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:' --dirs-only | head -n 10"
