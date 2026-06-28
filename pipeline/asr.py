"""ASR fallbacks: download audio once, then transcribe via API or local Whisper."""
from __future__ import annotations

import logging
import mimetypes
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

import config
from pipeline.models import Segment, SubtitleResult, VideoInfo

_model = None
log = logging.getLogger("asr")


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
    lines = [
        "# Netscape HTTP Cookie File",
        f".bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\t{config.BILIBILI_SESSDATA}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _find_ffmpeg() -> Optional[str]:
    candidates: list[str] = []
    configured = os.getenv("FFMPEG_PATH")
    if configured:
        candidates.append(configured)

    first = shutil.which("ffmpeg")
    if first:
        candidates.append(first)

    if os.name == "nt":
        try:
            found = subprocess.run(
                ["where.exe", "ffmpeg"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            candidates.extend(line.strip() for line in found.stdout.splitlines() if line.strip())
        except (OSError, subprocess.SubprocessError):
            pass

        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
            candidates.extend(str(path) for path in packages.glob("Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe"))

    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen or not os.path.isfile(candidate):
            continue
        seen.add(normalized)
        try:
            result = subprocess.run(
                [candidate, "-version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                return candidate
        except (OSError, subprocess.SubprocessError):
            continue
    return None

def download_audio(info: VideoInfo, page: Optional[int] = None) -> Path:
    """Download audio as a compact 16 kHz mono MP3 for ASR."""
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
    }

    if info.source == "bilibili":
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
    elif info.source == "youtube" and config.YOUTUBE_COOKIES and os.path.exists(config.YOUTUBE_COOKIES):
        opts["cookiefile"] = config.YOUTUBE_COOKIES

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    candidates = list(config.TMP_DIR.glob(out_base.name + ".*"))
    if not candidates:
        raise RuntimeError("音频下载失败，未找到输出文件")
    source_audio = candidates[0]

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        log.warning("ffmpeg not found; uploading the original audio file")
        return source_audio

    audio = out_base.with_suffix(".mp3")
    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-loglevel", "error", "-i", str(source_audio),
                "-vn", "-ar", "16000", "-ac", "1", "-b:a", "48k", str(audio),
            ],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"音频压缩失败: {exc}") from exc
    source_audio.unlink(missing_ok=True)
    return audio


def api_available() -> bool:
    return config.ASR_ENABLED and bool(config.ASR_API_KEY)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _segments_from_transcription_payload(payload: dict, duration_hint: int = 0) -> list[Segment]:
    segments: list[Segment] = []
    raw_segments = payload.get("segments")
    if isinstance(raw_segments, list):
        for raw in raw_segments:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or "").strip()
            if not text:
                continue
            start = _safe_float(raw.get("start"), 0.0)
            end = _safe_float(raw.get("end"), start)
            if end < start:
                end = start
            segments.append(Segment(start=start, end=end, text=text))
    if segments:
        return segments

    text = str(payload.get("text") or "").strip()
    if text:
        return [Segment(start=0.0, end=float(duration_hint or 0), text=text)]
    raise RuntimeError("ASR API returned no transcript text")


def transcribe_api(info: VideoInfo, page: Optional[int] = None) -> SubtitleResult:
    if not api_available():
        raise RuntimeError("ASR API is not configured")

    audio = download_audio(info, page)
    try:
        with audio.open("rb") as fh:
            content_type = mimetypes.guess_type(audio.name)[0] or "application/octet-stream"
            resp = requests.post(
                f"{config.ASR_BASE_URL}/audio/transcriptions",
                headers={"Authorization": f"Bearer {config.ASR_API_KEY}"},
                data={
                    "model": config.ASR_MODEL,
                },
                files={
                    "file": (audio.name, fh, content_type),
                },
                timeout=(300, 300),
            )
        resp.raise_for_status()
        payload = resp.json()
        segments = _segments_from_transcription_payload(payload, info.duration)
    except requests.HTTPError as exc:
        detail = exc.response.text[:400] if exc.response is not None else str(exc)
        log.warning("ASR API request failed: %s", detail)
        raise RuntimeError(f"ASR API请求失败: {detail}") from exc
    except ValueError as exc:
        raise RuntimeError("ASR API返回了无效JSON") from exc
    finally:
        try:
            audio.unlink(missing_ok=True)
        except OSError:
            pass

    return SubtitleResult(
        segments=segments,
        level="api",
        lan_doc=f"ASR API · {config.ASR_MODEL}",
    )


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
    return SubtitleResult(
        segments=segments,
        level="whisper",
        lan_doc=f"本地Whisper·{config.WHISPER_MODEL}",
    )
