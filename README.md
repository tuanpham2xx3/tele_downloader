# Telegram Chrome profile

Mở Telegram Web bằng một profile Chrome tách biệt, lưu cục bộ trong
`Chrome_Telegram_Profile`. Thư mục profile đã được loại khỏi Git để không commit
cookie, token, lịch sử hoặc dữ liệu đăng nhập.

Chạy từ PowerShell:

```powershell
.\start-chrome-telegram.ps1
```

Mở một URL Telegram khác:

```powershell
.\start-chrome-telegram.ps1 -Url "https://t.me/ten_bot_hoac_tool"
```

Đóng toàn bộ cửa sổ dùng profile này trước khi chạy lại script nếu Chrome báo
profile đang được sử dụng.
