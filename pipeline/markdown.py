"""把字幕片段渲染成 markdown 并落盘。"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import config
from pipeline.bilibili import Segment, SubtitleResult, VideoInfo

LEVEL_LABEL = {
    "cc": "B站CC字幕(人工)",
    "ai": "B站AI字幕",
    "whisper": "本地Whisper转写",
}


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


def render_markdown(info: VideoInfo, sub: SubtitleResult) -> str:
    lines: list[str] = []
    lines.append(f"# {info.title}")
    if info.page_title and info.page_title != info.title:
        lines.append(f"## {info.page_title}")
    lines.append("")
    lines.append(f"- 视频: https://www.bilibili.com/video/{info.bvid}")
    if info.owner:
        lines.append(f"- UP主: {info.owner}")
    lines.append(f"- 字幕来源: {LEVEL_LABEL.get(sub.level, sub.level)}"
                 + (f"（{sub.lan_doc}）" if sub.lan_doc else ""))
    lines.append(f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 带时间戳的逐条字幕
    lines.append("## 带时间戳字幕")
    lines.append("")
    for seg in sub.segments:
        lines.append(f"`[{_ts(seg.start)}]` {seg.text}")
    lines.append("")

    # 纯文本（按停顿补标点，便于阅读 / 喂给 LLM 做总结）
    lines.append("## 纯文本")
    lines.append("")
    lines.append(punctuate(sub.segments))
    lines.append("")
    return "\n".join(lines)


# 停顿阈值（秒）：大于句号阈值断句，大于逗号阈值断句为逗号，否则也补逗号保证可读
_PERIOD_GAP = 1.0
_COMMA_GAP = 0.3
_STRIP = "，。、！？!?,. "


def punctuate(segments) -> str:
    """B站AI字幕不带标点，依据相邻字幕的时间间隔补中文标点。"""
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


def save_markdown(info: VideoInfo, sub: SubtitleResult) -> Path:
    content = render_markdown(info, sub)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{stamp}_{_safe_filename(info.title)}.md"
    path = config.OUTPUT_DIR / fname
    path.write_text(content, encoding="utf-8")
    return path
