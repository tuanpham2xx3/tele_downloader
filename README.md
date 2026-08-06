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

Mỗi dòng TXT gồm tên khóa học in đậm trong tin nhắn, một ký tự tab và URL
**Get Files** tương ứng. Runner chấp nhận cả định dạng mới này lẫn file cũ chỉ
có URL. Với định dạng mới, runner hiển thị tên khóa học trong trạng thái, bảng
nhật ký và cột `course_title` của file CSV.

Chế độ thu thập chỉ chạy sau thao tác bấm của người dùng và chỉ quét tab
Telegram đang mở. Extension không truy cập cookie/token; quyền `tabs` và ba host
cụ thể chỉ phục vụ runner mô tả bên dưới.

## Mở bot từ danh sách TXT

Sau khi thu thập URL, mở popup extension và chọn **Xử lý danh sách TXT**. Chọn
file TXT đã lưu, đặt độ trễ và thời gian chờ trang ổn định, rồi bấm **Bắt đầu xử
lý**. Runner hiển thị mốc giờ thực tế khi mở URL (ví dụ `16:55 8/6/2026`), thời
gian đã dùng và ghi cả hai vào log. Với từng URL, công cụ sẽ:

1. Mở trang `www.cbusters.com`.
2. Bấm **Get Files (Alternate)**.
3. Trên trang `t.me`, bấm **OPEN IN WEB**.
4. Chờ Telegram Web tải xong, ghi log và đóng tab trung gian.

Runner có nút **Dừng** và xuất log CSV. Nó không bấm **START BOT**, không tải
file từ bot và không đọc cookie/token. Quyền `tabs` được dùng để quản lý tab tạm;
host access chỉ giới hạn ở `www.cbusters.com`, `t.me` và `web.telegram.org`.
Mỗi bước có thời gian chờ hữu hạn; runner chỉ bấm đúng nút **OPEN IN WEB** và thử
lại nếu trang chưa chuyển. Link lỗi được ghi vào log và hàng đợi tiếp tục chạy.

### Đối chiếu file trong bot

Sau khi nạp TXT có tên khóa học, mở chat bot trong một tab Telegram Web rồi quay
lại runner và chọn **Dò tên trong bot**. Extension cuộn lịch sử bot, đọc các tiêu
đề in đậm và so với file gốc. Kết quả gồm **Có**, **Gần giống** và **Thiếu**, có
thể xuất thành CSV để kiểm tra. Chức năng này chỉ đọc nội dung đang hiển thị trong
Telegram Web; không bấm bot hoặc tải file.
