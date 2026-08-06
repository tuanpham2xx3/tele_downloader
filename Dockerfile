FROM python:3.10-slim

# Thiết lập môi trường
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Cài đặt các công cụ hệ thống (7z, unrar, rclone, curl, bash)
RUN apt-get update && apt-get install -y --no-install-recommends \
    p7zip-full \
    unrar-free \
    rclone \
    curl \
    ca-certificates \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Copy file requirements và cài đặt Python dependencies
COPY telegram_media_downloader/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir telethon rich python-dotenv pyyaml requests

# Copy toàn bộ mã nguồn ứng dụng vào Container
COPY . /app

# Phân quyền thực thi các script bash
RUN chmod +x /app/start-pipeline.sh /app/manage.sh

# Mở cổng 5000 cho Web Log Monitor
EXPOSE 5000

# Mặc định khởi chạy Pipeline
CMD ["/app/start-pipeline.sh"]
