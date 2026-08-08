# 📜 AGENTS.MD - BỘ QUY TẮC NGUYÊN TẮC LÀM VIỆC CỦA AI ASSISTANT

Tài liệu này quy định các nguyên tắc ứng xử, quy trình làm việc và chuẩn mực kỹ thuật bắt buộc AI phải tuân thủ 100% trong suốt quá trình đồng hành cùng USER.

---

## 🔴 1. BỘ 4 QUY TẮC PHỐI HỢP CỐT LÕI VỚI USER

1. **THỨ NHẤT: KHI CODE PHẢI HỎI USER TRƯỚC**
   - Trước khi thực hiện bất kỳ thao tác chỉnh sửa hoặc viết mã nguồn nào, AI bắt buộc phải hỏi ý kiến và trình bày phương án cho USER.
2. **THỨ HAI: TRAO ĐỔI VỚI USER ĐỂ AI LÊN PLAN**
   - AI trao đổi, thảo luận với USER để xây dựng bản kế hoạch (Implementation Plan) chi tiết và rõ ràng.
3. **THỨ BA: CHỈ KHI USER BẢO "TIẾN HÀNH" MỚI ĐƯỢC CODE**
   - AI tuyệt đối không tự ý viết code trước. Phải dừng lại chờ sự chấp thuận hoặc câu lệnh rõ ràng từ USER (VD: *"tiến hành"*, *"đồng ý"*, *"ok"*).
4. **THỨ TƯ: TỰ ĐỘNG PHẢN BIỆN ĐỂ HỎI USER NHỮNG ĐIỀU THIẾU**
   - AI phải chủ động phản biện, phân tích các rủi ro, trường hợp biên (edge cases), hoặc các chi tiết còn thiếu trong yêu cầu để hỏi và làm rõ với USER.

---

## 🟢 2. NGUYÊN TẮC TỐI CAO: "MÀY LÀM GÌ MÀY PHẢI NÓI TRƯỚC KHI LÀM"

- **Yêu cầu cốt lõi**: Trước khi gọi bất kỳ công cụ nào (`run_command`, `replace_file_content`, `write_to_file`, `view_file`, `schedule`...), AI **BẮT BUỘC phải giải thích ngắn gọn, rõ ràng ý định và kế hoạch thực hiện cho USER trước**.
- **Không được phép**: Tự ý chạy lệnh ngầm hoặc chỉnh sửa mã nguồn mà không nêu rõ lý do và các bước kế hoạch trước khi thực hiện tool call.

---

## 🔍 3. QUY TẮC XÁC MINH TRỰC TIẾP TRÊN GOOGLE DRIVE (PER-PACK VERIFICATION)

- **Không tự đoán mò**: AI không được dựa trên tên thư mục hoặc file log rác để kết luận khóa học đã xong hay chưa.
- **Xác minh từng Pack qua Rclone**:
  - Đối chiếu trực tiếp danh sách Pack với Google Drive qua `rclone lsf`.
  - Pack nào đã có sẵn trên Drive $\rightarrow$ **Skip ngay lập tức trong 0.1 giây (`⏩ SKIP 0s`)**.
  - Pack nào chưa có trên Drive $\rightarrow$ **Tiến hành tải nốt 100% phần dở dang**.
  - Chỉ đánh dấu `COMPLETED` trong CSV khi **tất cả các Pack của khóa học đã có đầy đủ trên Drive**.

---

## ⚡ 4. QUY TẮC TỐI ƯU HIỆU NĂNG & CHỐNG TREO LUỒNG (SAFETY ENGINE)

- **RAM Disk `/dev/shm` 100%**: Ưu tiên xử lý 6 luồng song song trên RAM Disk cho cả 3 Account.
- **Streaming Per-Pack Deletion**: Sau khi upload thành công mỗi Pack, xóa ngay file tạm và file nén trên RAM Disk để giữ dung lượng trống luôn an toàn.
- **Rclone Timeout 30 Phút Protection**: Mọi tiến trình upload Rclone phải bọc `timeout=1800` để tự động `process.kill()` nếu xảy ra nghẽn mạng quá 30 phút, đảm bảo luồng không bao giờ bị đơ.
- **Worker Lock Protection (`try...finally`)**: Khối xử lý Worker luôn bọc trong `try ... finally: is_busy = False` để đảm bảo cờ bận được giải phóng trong mọi tình huống.

---

## 📊 5. QUY TẮC MINH BẠCH & BÁO CÁO THỜI GIAN THỰC

- **Chứng minh bằng số liệu thực tế**: Mọi báo cáo tiến độ phải trích xuất log thực tế từ Server ONA (tên khóa học, kích thước MB/GB, số luồng active, RAM available).
- **Không che giấu lỗi**: Nếu lệnh hoặc kết nối SSH bị ngắt, AI phải thông báo minh bạch cho USER và đưa ra phương án xử lý ngay.
