FROM python:3.10-slim

# Cài đặt FFmpeg và các công cụ bổ trợ
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Thiết lập thư mục làm việc
WORKDIR /app

# Sao chép file requirements và cài đặt thư viện
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn vào container
COPY . .

# Mặc định khởi chạy (sẽ chạy trực tiếp file video_pipeline.py)
ENTRYPOINT ["python", "video_pipeline.py"]
