FROM python:3.10-slim

# Cài đặt các thư viện hệ thống cần thiết (FFmpeg, ffprobe, certificates)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Thiết lập thư mục làm việc
WORKDIR /app

# Thiết lập các biến môi trường cần thiết
ENV PYTHONUNBUFFERED=1
ENV RUNNING_IN_DOCKER=1

# Sao chép và cài đặt các thư viện Python trước để tối ưu hóa cache lớp của Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn vào container
COPY . .

# Điểm khởi chạy mặc định:
# - Chạy mặc định sẽ khởi chạy queue_run.py
# - Có thể thay thế bằng auto_run.py hoặc video_pipeline.py khi chạy docker run
ENTRYPOINT ["python3"]
CMD ["queue_run.py"]
