# Telegram Get Files & Automated Course Downloader Pipeline

Hệ thống công cụ khép kín dùng để **thu thập tiêu đề/liên kết khóa học Telegram Web** qua Extension Chrome MV3 và **tự động hóa rà quét, tải xuống, giải nén, upload Google Drive qua Rclone & dọn dẹp đĩa** tối ưu cho **Ubuntu Server**.

---

## 🛠 Kiến trúc Hệ thống

```
_GETURL/
├── telegram-link-collector/     # Extension Chrome MV3 (Thu thập & Đối chiếu tiêu đề)
│   ├── manifest.json            # Extension v1.6.0
│   ├── popup.html / popup.js    # Giao diện Popup 3 mục riêng biệt
│   └── runner.html / runner.js  # Trình tự động mở shortlink Get Files
├── telegram_media_downloader/   # Module Downloader & Engine Pyrogram/Telethon
│   ├── course_pipeline.py       # Pipeline tự động 6 bước khép kín
│   └── full_hoahoc.csv          # Cơ sở dữ liệu danh sách khóa & trạng thái COMPLETED
├── start-chrome-telegram.ps1    # Script khởi chạy Chrome Profile riêng biệt
├── start-pipeline.sh            # Script khởi chạy Pipeline trên UBUNTU SERVER
└── start-pipeline.ps1           # Script khởi chạy Pipeline trên WINDOWS
```

---

## 🧩 1. Extension Chrome MV3 (`telegram-link-collector`)

Phân chia làm **3 mục chức năng độc lập**:
1. **QUÉT GROUP CON (LẤY URL)**: Quét link `Get Files` + Tên khóa học từ các kênh/nhóm con.
2. **QUÉT CHAT BOT (LẤY TÊN KHÓA HỌC)**: Quét tự động danh sách tên khóa học trực tiếp trong Bot (không bị cấm/nạp file), tự động lọc bỏ 100% rác tin nhắn (đuôi `.rar`, `.zip`, dung lượng `MB`, note,...).
3. **ĐỐI CHIẾU BOT VỚI FILE TXT**: So sánh danh sách khóa thiếu/trùng giữa file TXT gốc và Bot hiện tại.

Khởi chạy Chrome:
```powershell
.\start-chrome-telegram.ps1
```

---

## 🚀 2. Pipeline Tự Động Hóa 6 Bước (`course_pipeline.py`)

Quy trình tự động hóa tuần tự cho từng khóa học:

```
[1. Load tin nhắn Bot] ➔ [2. Detect Khóa & Gom File Stream] ➔ [3. Tải từng khóa (Single Queue)]
                                                                           │
[6. Xóa đĩa Ubuntu & Lưu CSV] ◄── [5. Rclone Upload Drive] ◄── [4. Giải nén .mp4 & Class_Materials.zip]
```

1. **Load tin nhắn Bot**: Đọc luồng tin nhắn từ Telegram Bot (`@coursebusters_bot`).
2. **Detect Khóa & Gom File**: Nhận diện thẻ bài đăng khóa học và gom toàn bộ file đính kèm (`.rar`, `.zip`) đứng sau vào khóa đó.
3. **Tải từng khóa**: Tải tuần tự từng khóa học vào thư mục tạm `./temp_processing/` để tiết kiệm tối đa đĩa Ubuntu.
4. **Giải nén & Đóng gói**:
   * Đưa toàn bộ video **`.mp4` / `.mkv`** ra thư mục upload.
   * Gom tất cả tài liệu còn lại (PSD, CLIP, PDF, BRUSH...) nén thành **1 file `Class_Materials.zip` duy nhất**.
5. **Upload Google Drive qua Rclone**:
   * Kiểm tra và tải lên thư mục cha định sẵn trên Google Drive (`RCLONE_PARENT_FOLDER`).
6. **Chống trùng 2 lớp, Dọn dẹp & Lưu CSV**:
   * Tự động kiểm tra file `full_hoahoc.csv` và Rclone `lsf` trước khi tải. Nếu khóa đã tồn tại ➔ Bỏ qua.
   * Xóa sạch tài nguyên tạm trên đĩa Ubuntu.
   * Lưu trạng thái `COMPLETED` kèm timestamp vào `full_hoahoc.csv`.

---

## 🌐 3. Web Log Monitor từ xa (Cổng 5000)

Khi khởi chạy pipeline trên Ubuntu, hệ thống tự động bật Web Server theo dõi Log thời gian thực:
* **Địa chỉ truy cập**: `http://<IP_UBUNTU_SERVER>:5000`
* **Tính năng**:
  * Theo dõi Live Log 24/7 với highlight màu sắc trực quan (`[SUCCESS]`, `[ERROR]`, `[WARN]`, `[INFO]`).
  * Nút **📥 Xuất Log (.txt)**: Tải toàn bộ log file về máy tính.
  * Nút **📊 Tải CSV Status**: Tải trực tiếp file `full_hoahoc.csv` về máy.

---

## 🏃 Hướng dẫn Khởi chạy Pipeline

### Trên Ubuntu Server:
```bash
chmod +x start-pipeline.sh
./start-pipeline.sh -r "gdrive:/COURSES_FOLDER" -p 5000
```

### Trên Windows (để kiểm thử):
```powershell
.\start-pipeline.ps1 -RcloneDest "gdrive:/COURSES_FOLDER" -Port 5000
```
