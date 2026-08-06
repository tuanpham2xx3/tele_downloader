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

## Telerecon

Telerecon được tích hợp dưới dạng Git submodule và chạy trong môi trường Python
riêng. Chỉ dùng để nghiên cứu dữ liệu công khai hoặc nội dung bạn có quyền truy
cập, đồng thời tuân thủ điều khoản của Telegram và pháp luật áp dụng.

Chuẩn bị lần đầu:

```powershell
git submodule update --init
.\install-telerecon.ps1
.\configure-telerecon.ps1
```

Lấy API ID và API Hash của chính tài khoản bạn tại `my.telegram.org`. Credential
được Windows mã hóa vào `.telerecon-credentials.xml` cho user/máy hiện tại và
không được Git theo dõi. Không chạy `Telerecon\setup.py`, vì script upstream ghi
credential dạng văn bản thuần vào source tree.

Mở đồng thời Telegram Web và menu Telerecon:

```powershell
.\start-get-tool.ps1
```

Chỉ mở Telerecon:

```powershell
.\start-get-tool.ps1 -SkipTelegram
```

## Thu thập nút Get Files trong group con

`telegram-link-collector` là extension MV3 cục bộ. Script mở Chrome sẽ tự nạp
extension này. Nếu profile đang mở từ trước, đóng các cửa sổ của profile
`Chrome_Telegram_Profile`, sau đó chạy lại:

```powershell
.\start-chrome-telegram.ps1
```

Trong Telegram Web:

1. Mở group chính rồi vào đúng group con cần thu thập.
2. Bấm biểu tượng **Telegram Get Files URL Collector** trên thanh extension.
3. Chọn **Quét toàn bộ group con**.
4. Kiểm tra kết quả rồi chọn **Lưu TXT**.

Extension chỉ có `activeTab`, `scripting` và `downloads`. Nó chỉ chạy sau thao
tác bấm của người dùng, chỉ quét tab Telegram đang mở, không mở các URL đích và
không truy cập cookie/token.
