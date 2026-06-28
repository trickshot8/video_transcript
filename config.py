"""集中读取配置（来自环境变量 / .env）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Windows 控制台默认 GBK，输出 emoji/特殊字符会 UnicodeEncodeError，统一切到 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

BASE_DIR = Path(__file__).resolve().parent

BILIBILI_SESSDATA = os.getenv("BILIBILI_SESSDATA", "").strip()

# YouTube cookies 文件路径(Netscape 格式)。YouTube 对字幕下载限流较狠，
# 提供登录态 cookies 可大幅缓解 429。留空则不带 cookies。
YOUTUBE_COOKIES = os.getenv("YOUTUBE_COOKIES", "").strip()

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8765"))
API_TOKEN = os.getenv("API_TOKEN", "").strip()

_output = os.getenv("OUTPUT_DIR", "output").strip()
OUTPUT_DIR = Path(_output) if os.path.isabs(_output) else BASE_DIR / _output
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 是否启用本地 Whisper 兜底。树莓派等弱算力设备建议关掉（设为 false / 0 / no）
ENABLE_WHISPER = os.getenv("ENABLE_WHISPER", "true").strip().lower() not in ("0", "false", "no", "")

# ===== 云 ASR 兜底（无字幕视频时用，OpenAI 兼容 /audio/transcriptions）=====
# 默认硅基流动 + SenseVoiceSmall（免费、中文强）。留空 key 则不启用，无字幕直接回执。
ASR_ENABLED = os.getenv("ASR_ENABLED", "true").strip().lower() not in ("0", "false", "no", "")
ASR_API_KEY = os.getenv("ASR_API_KEY", "").strip()
ASR_BASE_URL = os.getenv("ASR_BASE_URL", "https://api.siliconflow.cn/v1").strip().rstrip("/")
ASR_MODEL = os.getenv("ASR_MODEL", "FunAudioLLM/SenseVoiceSmall").strip()

# ===== 字幕总结（服务端 LLM，默认 DeepSeek，OpenAI 兼容接口）=====
SUMMARY_ENABLED = os.getenv("SUMMARY_ENABLED", "true").strip().lower() not in ("0", "false", "no", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
SUMMARY_BASE_URL = os.getenv("SUMMARY_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "deepseek-chat").strip()

# 性能记录中的设备标签。Docker 部署建议设置为 pi5、mac-mini-m4 等易读名称。
PERF_HOST_LABEL = os.getenv("PERF_HOST_LABEL", "").strip()

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small").strip()
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu").strip()
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip()

# 临时音频下载目录
TMP_DIR = BASE_DIR / ".tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
