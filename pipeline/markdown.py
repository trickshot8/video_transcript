"""Render subtitle segments to markdown and save them."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import config
from pipeline.models import Segment, SubtitleResult, VideoInfo

_LABELS = {
    "bilibili": {
        "cc": "B站CC字幕(人工)",
        "ai": "B站AI字幕",
        "api": "SenseVoiceSmall API转写",
        "whisper": "本地Whisper转写",
    },
    "youtube": {
        "cc": "YouTube字幕",
        "ai": "YouTube自动字幕",
        "api": "SenseVoiceSmall API转写",
        "whisper": "本地Whisper转写",
    },
}


def label(source: str, level: str) -> str:
    return _LABELS.get(source, {}).get(level, level)


def _ts(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _safe_filename(name: str, limit: int = 60) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip()
    return (name[:limit] or "untitled").rstrip(". ")


def render_markdown(info: VideoInfo, sub: SubtitleResult, summary: str = "") -> str:
    lines: list[str] = []
    lines.append(f"# {info.title}")
    if info.page_title and info.page_title != info.title:
        lines.append(f"## {info.page_title}")
    lines.append("")
    lines.append(f"- 视频: {info.url}")
    if info.owner:
        lines.append(f"- {'UP主' if info.source == 'bilibili' else '频道'}: {info.owner}")
    lines.append(f"- 字幕来源: {label(info.source, sub.level)}" + (f"（{sub.lan_doc}）" if sub.lan_doc else ""))
    lines.append(f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    if summary:
        lines.append("## 摘要")
        lines.append("")
        lines.append(summary)
        lines.append("")

    lines.append("---")
    lines.append("")
    # API ASR 通常只返回整段无时间戳的文本，带时间戳的区块没有意义，跳过。
    if sub.level != "api":
        lines.append("## 带时间戳字幕")
        lines.append("")
        for seg in sub.segments:
            lines.append(f"`[{_ts(seg.start)}]` {seg.text}")
        lines.append("")

    lines.append("## 纯文本")
    lines.append("")
    lines.append(punctuate(sub.segments))
    lines.append("")
    return "\n".join(lines)


_PERIOD_GAP = 1.0
_STRIP = "，。、！？!?,. "


def punctuate(segments: list[Segment]) -> str:
    parts: list[str] = []
    n = len(segments)
    for i, seg in enumerate(segments):
        text = seg.text.strip().rstrip(_STRIP)
        if not text:
            continue
        parts.append(text)
        if i == n - 1:
            parts.append("。")
            break
        gap = segments[i + 1].start - seg.end
        parts.append("。" if gap >= _PERIOD_GAP else "，")
    return "".join(parts)


def save_markdown(info: VideoInfo, sub: SubtitleResult, summary: str = "") -> Path:
    content = render_markdown(info, sub, summary=summary)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{stamp}_{_safe_filename(info.title)}.md"
    path = config.OUTPUT_DIR / fname
    path.write_text(content, encoding="utf-8")
    return path
