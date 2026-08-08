# Script 1-Click dong bo nhat ky tu Google Drive (_SYSTEM_METADATA/) ve may local
$rcloneDest = "gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:"
$localDir = "c:\PROJECT\_EXTENTSION\_GETURL"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  DONG BO NHAT KY TU GOOGLE DRIVE VE LOCAL" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

rclone copyto "$rcloneDest/_SYSTEM_METADATA/upload_pack_tracker.json" "$localDir\upload_pack_tracker.json"
rclone copyto "$rcloneDest/_SYSTEM_METADATA/upload_pack_tracker.csv" "$localDir\upload_pack_tracker.csv"

Write-Host "`n[OK] Da dong bo nhat ky moi nhat tu Google Drive ve may local!" -ForegroundColor Green
Write-Host "File JSON: $localDir\upload_pack_tracker.json" -ForegroundColor Yellow
Write-Host "File CSV:  $localDir\upload_pack_tracker.csv" -ForegroundColor Yellow
