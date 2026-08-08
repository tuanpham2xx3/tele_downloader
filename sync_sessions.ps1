$vpsHost = "019fe046-2e97-7ba9-9e28-cf3b378e3148.gitpod.environment"

Write-Host "=========================================="
Write-Host "🚀 ĐỒNG BỘ SESSION TELEGRAM SANG VPS ONA VIA SCP"
Write-Host "=========================================="

Write-Host "[1/3] Tạo thư mục lưu trữ session trên VPS..."
ssh -o StrictHostKeyChecking=no $vpsHost "mkdir -p /home/codespace/.telegram_sessions /workspaces/tele_downloader/telegram_media_downloader"

Write-Host "[2/3] Uploading pyrogram.session (Acc 1 Master)..."
scp -o StrictHostKeyChecking=no "c:\PROJECT\_EXTENTSION\_GETURL\telegram_media_downloader\pyrogram.session" "${vpsHost}:/home/codespace/.telegram_sessions/pyrogram.session"
scp -o StrictHostKeyChecking=no "c:\PROJECT\_EXTENTSION\_GETURL\telegram_media_downloader\pyrogram.session" "${vpsHost}:/workspaces/tele_downloader/telegram_media_downloader/pyrogram.session"

Write-Host "[2/3] Uploading pyrogram_acc2.session (Acc 2 Relay)..."
scp -o StrictHostKeyChecking=no "c:\PROJECT\_EXTENTSION\_GETURL\telegram_media_downloader\pyrogram_acc2.session" "${vpsHost}:/home/codespace/.telegram_sessions/pyrogram_acc2.session"
scp -o StrictHostKeyChecking=no "c:\PROJECT\_EXTENTSION\_GETURL\telegram_media_downloader\pyrogram_acc2.session" "${vpsHost}:/workspaces/tele_downloader/telegram_media_downloader/pyrogram_acc2.session"

Write-Host "[2/3] Uploading pyrogram_acc3.session (Acc 3 Relay)..."
scp -o StrictHostKeyChecking=no "c:\PROJECT\_EXTENTSION\_GETURL\telegram_media_downloader\pyrogram_acc3.session" "${vpsHost}:/home/codespace/.telegram_sessions/pyrogram_acc3.session"
scp -o StrictHostKeyChecking=no "c:\PROJECT\_EXTENTSION\_GETURL\telegram_media_downloader\pyrogram_acc3.session" "${vpsHost}:/workspaces/tele_downloader/telegram_media_downloader/pyrogram_acc3.session"

Write-Host "[3/3] Restarting Pipelines trên VPS ONA..."
ssh -o StrictHostKeyChecking=no $vpsHost "cd /workspaces/tele_downloader && ./start-multi-pipeline.sh"

Write-Host "=========================================="
Write-Host "✅ ĐỒNG BỘ KẾT NỐI HOÀN TẤT!"
Write-Host "=========================================="
