"""本地兜底：yt-dlp 下载音频 -> faster-whisper 转写中文。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import config
from pipeline.models import Segment, SubtitleResult, VideoInfo

_model = None  # 懒加载，避免没用到时也吃内存


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
        )
    return _model


def _write_cookiefile() -> Optional[str]:
    if not config.BILIBILI_SESSDATA:
        return None
    path = config.TMP_DIR / "bili_cookies.txt"
    # Netscape cookie 格式
    lines = [
        "# Netscape HTTP Cookie File",
        f".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\t{config.BILIBILI_SESSDATA}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def download_audio(info: VideoInfo, page: Optional[int] = None) -> Path:
    """下载视频音轨为 16k 单声道 wav，返回文件路径。B站/YouTube 通用。"""
    import yt_dlp

    url = info.url
    if info.source == "bilibili" and page:
        url += f"?p={page}"

    out_base = config.TMP_DIR / f"{info.video_id}_{page or 1}_{int(time.time())}"
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out_base) + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
        }],
        # 转成 whisper 友好的 16k 单声道
        "postprocessor_args": ["-ar", "16000", "-ac", "1"],
    }
    if info.source == "bilibili":
        # 带上浏览器 UA + Referer，规避 B站风控的 HTTP 412
        opts["http_headers"] = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Referer": "https://www.bilibili.com/",
        }
        cookiefile = _write_cookiefile()
        if cookiefile:
            opts["cookiefile"] = cookiefile
    elif info.source == "youtube" and config.YOUTUBE_COOKIES:
        opts["cookiefile"] = config.YOUTUBE_COOKIES

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    wav = out_base.with_suffix(".wav")
    if not wav.exists():
        # 兜底找同前缀的产物
        candidates = list(config.TMP_DIR.glob(out_base.name + ".*"))
        if not candidates:
            raise RuntimeError("音频下载失败，未找到产物文件")
        wav = candidates[0]
    return wav


def transcribe_local(info: VideoInfo, page: Optional[int] = None) -> SubtitleResult:
    audio = download_audio(info, page)
    try:
        model = _get_model()
        segments_iter, _ = model.transcribe(
            str(audio),
            language="zh",
            vad_filter=True,
            beam_size=5,
        )
        segments = [
            Segment(start=float(s.start), end=float(s.end), text=s.text.strip())
            for s in segments_iter
            if s.text.strip()
        ]
    finally:
        try:
            audio.unlink(missing_ok=True)
        except OSError:
            pass
    if not segments:
        raise RuntimeError("Whisper 未识别出任何文本")
    return SubtitleResult(segments=segments, level="whisper",
                          lan_doc=f"本地Whisper·{config.WHISPER_MODEL}")
