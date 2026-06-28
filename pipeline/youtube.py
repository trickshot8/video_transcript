"""YouTube 链接解析 + 中文字幕抓取，用 yt-dlp。

字幕优先级：人工中文 > 自动中文（含 YouTube 自动翻译成中文）。
取不到中文字幕则返回 None，交给上层走 Whisper 兜底。
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

import config
from pipeline.models import Segment, SubtitleResult, VideoInfo

_YT_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^ ]*&)*v=|shorts/|embed/|live/|v/))"
    r"([A-Za-z0-9_-]{11})"
)
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# 中文字幕优先级（含简/繁/自动翻译目标）
_ZH_LANGS = ["zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW", "zh-HK"]

# 单条缓存：同一请求里 get_video_info 与 fetch_subtitle 复用同一次 extract，不重复联网
_last: dict = {"id": None, "info": None}


def _base_opts() -> dict:
    """yt-dlp 通用选项：静默 + 重试 + (可选)cookies 缓解限流。"""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extractor_retries": 3,
        "retries": 3,
    }
    # 仅当 cookies 文件确实存在时才用——路径设了但文件没放也不会报错
    if config.YOUTUBE_COOKIES and os.path.exists(config.YOUTUBE_COOKIES):
        opts["cookiefile"] = config.YOUTUBE_COOKIES
    return opts


def is_youtube(text: str) -> bool:
    return _YT_RE.search(text) is not None


def extract_id(text: str) -> str:
    m = _YT_RE.search(text.strip())
    if m:
        return m.group(1)
    if _ID_RE.match(text.strip()):
        return text.strip()
    raise ValueError(f"无法从输入中识别 YouTube 视频 ID: {text!r}")


def _extract(video_id: str) -> dict:
    if _last["id"] == video_id and _last["info"] is not None:
        return _last["info"]
    import yt_dlp

    opts = {**_base_opts(), "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
    _last["id"] = video_id
    _last["info"] = info
    return info


def get_video_info(video_id: str) -> VideoInfo:
    info = _extract(video_id)
    return VideoInfo(
        video_id=video_id,
        source="youtube",
        url=info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
        title=info.get("title", ""),
        page_title=info.get("title", ""),
        owner=info.get("uploader") or info.get("channel") or "",
        duration=int(info.get("duration") or 0),
    )


def _first_present(captions: dict, langs: list[str]) -> Optional[str]:
    for lang in langs:
        if lang and captions.get(lang):
            return lang
    return None


def _native_auto_lang(autos: dict) -> Optional[str]:
    """自动字幕里挑"原生"(非翻译)语言：其格式 URL 不带 tlang= 的那个。"""
    for lang, fmts in autos.items():
        if any("tlang=" not in (f.get("url") or "") for f in fmts):
            return lang
    return None


def fetch_subtitle(info: VideoInfo) -> Optional[SubtitleResult]:
    """按"原语言"取字幕，避开 YouTube 对自动翻译(tlang)的强限流。

    人工字幕：中文优先 > 视频原语言 > 任意。
    自动字幕：只取原语言(native，不翻译)——中文视频原语言即中文。
    摘要由上层用 DeepSeek 生成，始终中文，与字幕语言无关。
    """
    raw = _extract(info.video_id)
    manual = raw.get("subtitles") or {}
    autos = raw.get("automatic_captions") or {}
    orig = raw.get("language") or ""

    # 1. 人工字幕（创作者上传，准确，无翻译限流问题）
    lang = _first_present(manual, _ZH_LANGS + [orig] + sorted(manual.keys()))
    if lang:
        segs = _download_and_parse(info.video_id, lang, manual=True)
        if segs:
            return SubtitleResult(segs, "cc", f"YouTube {lang}")

    # 2. 自动字幕，只取原语言(native)
    auto_lang = orig if autos.get(orig) else _native_auto_lang(autos)
    if auto_lang:
        segs = _download_and_parse(info.video_id, auto_lang, manual=False)
        if segs:
            return SubtitleResult(segs, "ai", f"YouTube {auto_lang}(自动)")
    return None


def _download_and_parse(video_id: str, lang: str, manual: bool) -> list[Segment]:
    """用 yt-dlp 把指定语言字幕下成 json3，读出来解析，再清理。"""
    import yt_dlp

    base = config.TMP_DIR / f"yt_{video_id}_{int(time.time())}"
    opts = {
        **_base_opts(),
        "skip_download": True,
        "writesubtitles": manual,
        "writeautomaticsub": not manual,
        "subtitleslangs": [lang],
        "subtitlesformat": "json3",
        "outtmpl": str(base),
        "sleep_interval_subtitles": 1,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    except Exception:  # noqa: BLE001
        return []

    files = list(config.TMP_DIR.glob(base.name + "*.json3"))
    if not files:
        return []
    try:
        data = json.loads(files[0].read_text(encoding="utf-8"))
        return _parse_json3(data)
    finally:
        for f in files:
            f.unlink(missing_ok=True)


def _parse_json3(data: dict) -> list[Segment]:
    segs: list[Segment] = []
    for ev in data.get("events", []):
        if "segs" not in ev:
            continue
        text = "".join(s.get("utf8", "") for s in ev["segs"]).strip()
        if not text:
            continue
        start = ev.get("tStartMs", 0) / 1000
        dur = ev.get("dDurationMs", 0) / 1000
        segs.append(Segment(start=start, end=start + dur, text=text))
    return segs
