"""跨来源共享的数据结构（B站 / YouTube 通用）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Segment:
    start: float  # 秒
    end: float
    text: str


@dataclass
class SubtitleResult:
    segments: list[Segment]
    level: str          # cc 人工 / ai 自动 / whisper 本地转写
    lan_doc: str        # 语言/来源描述


@dataclass
class VideoInfo:
    video_id: str       # B站 BV号 / YouTube 视频id
    source: str         # "bilibili" / "youtube"
    title: str
    url: str            # 规范的观看链接
    owner: str = ""
    duration: int = 0   # 秒
    page_title: str = ""
    cid: int = 0        # 仅 B站：取字幕需要
