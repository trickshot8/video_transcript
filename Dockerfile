# 树莓派/ARM 部署用的精简镜像：只跑 B站 CC/AI 字幕（不含本地 Whisper）。
# python:slim 有 arm64 变体，适配 64位树莓派系统(Pi 4/5)。
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 仅装精简依赖（flask/requests/dotenv），不含 faster-whisper/ctranslate2/yt-dlp
COPY requirements-lite.txt .
RUN pip install --no-cache-dir -r requirements-lite.txt

COPY . .

# 容器内默认：关 Whisper，输出到挂载点 /data/subtitles
ENV HOST=0.0.0.0 \
    PORT=8765 \
    ENABLE_WHISPER=false \
    OUTPUT_DIR=/data/subtitles \
    PYTHONUNBUFFERED=1

EXPOSE 8765

CMD ["python", "server.py"]
