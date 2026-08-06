# Telegram Auto File Downloader

Công cụ tự động rà quét và tải toàn bộ file (.rar, .zip, .mp4, .pdf, ...) từ Bot/Channel Telegram dựa trên danh sách khóa học được xuất từ **Telegram Link Collector Extension**.

---

## 🛠 Tính năng chính
* **Tự động đăng nhập**: Tích hợp mã hóa Windows credential từ `.telerecon-credentials.xml` (dùng chung API ID/Hash của Telerecon).
* **Đọc file danh sách linh hoạt**: Tự động nhận diện định dạng file TXT xuất từ Extension (`Tên khóa học <TAB> URL` hoặc chỉ danh sách Tên khóa học).
* **Tự động tìm kiếm & Tải file đính kèm**: Rà quét các tin nhắn chứa file đính kèm trong Bot (`@coursebusters_bot` hoặc bot tùy chọn).
* **Thanh tiến trình trực quan (`rich`)**: Hiển thị tốc độ tải (MB/s), thời gian còn lại (ETA), dung lượng và thanh phần trăm trực tiếp trên Terminal.
* **Tổ chức thư mục khoa học**: Tự động phân loại file tải về vào thư mục riêng cho từng khóa học (ví dụ: `./downloads/<Tên Khóa Học>/file.rar`).
* **Tránh tải trùng**: Tự động bỏ qua các file đã tải đủ dung lượng.

---

## 🚀 Hướng dẫn sử dụng

### 1. Chạy nhanh bằng PowerShell Script (Khuyên dùng)

Mở PowerShell tại thư mục dự án và chạy:

```powershell
.\telegram-downloader\start-downloader.ps1
```

Script sẽ tự chọn file `.txt` danh sách mới nhất và bắt đầu rà tải vào thư mục `..\downloads`.

### 2. Tùy chỉnh file TXT hoặc Bot đích

Chỉ định file TXT danh sách khóa học:
```powershell
.\telegram-downloader\start-downloader.ps1 -InputFile "C:\path\to\danh_sach.txt"
```

Chỉ định Bot hoặc Channel khác:
```powershell
.\telegram-downloader\start-downloader.ps1 -TargetChat "@ten_bot_khac"
```

---

## ⚙️ Cấu hình nâng cao (`config.json`)

Bạn có thể chỉnh sửa file `telegram-downloader/config.json`:
- `target_chat`: Username của Bot mặc định.
- `download_dir`: Thư mục lưu file tải về.
- `allowed_extensions`: Danh sách định dạng đuôi file cho phép tải (`.rar`, `.zip`, `.7z`, `.mp4`, v.v.).
- `max_concurrent_downloads`: Số lượng file tải song song.
