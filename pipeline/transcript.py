"""三级 fallback 编排：B站CC字幕 -> B站AI字幕 -> 本地Whisper。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pipeline import asr, bilibili
from pipeline.markdown import LEVEL_LABEL, punctuate, save_markdown

log = logging.getLogger("transcript")


@dataclass
class PipelineResult:
    title: str
    bvid: str
    level: str               # cc / ai / whisper
    source_label: str
    segment_count: int
    file_path: str
    preview: str             # 纯文本前若干字，给通知用
    text: str = ""           # 完整字幕纯文本(带标点)，给快捷指令复制用
    attempts: list[str] = field(default_factory=list)


def run(raw_url: str, allow_whisper: bool = True) -> PipelineResult:
    attempts: list[str] = []
    vid, page = bilibili.resolve_url(raw_url)
    info = bilibili.get_video_info(vid, page)
    log.info("视频: %s (%s) cid=%s", info.title, info.bvid, info.cid)

    sub: Optional[bilibili.SubtitleResult] = None

    # 1+2 级：B站字幕（内部已优先CC，其次AI）
    try:
        sub = bilibili.fetch_bilibili_subtitle(info)
        if sub:
            attempts.append(f"B站{sub.level}字幕命中")
        else:
            attempts.append("B站无可用字幕")
    except Exception as e:  # noqa: BLE001  网络/接口异常都降级
        attempts.append(f"B站字幕抓取异常: {e}")
        log.warning("B站字幕抓取异常: %s", e)

    # 3 级：本地 whisper
    if sub is None and allow_whisper:
        log.info("降级到本地 Whisper 转写…")
        sub = asr.transcribe_local(info, page)
        attempts.append("本地Whisper转写完成")

    if sub is None:
        if not allow_whisper:
            raise RuntimeError("该视频无B站字幕，且本地Whisper转写已关闭")
        raise RuntimeError("未能获取字幕，本地转写也失败。尝试记录: " + "; ".join(attempts))

    path = save_markdown(info, sub)
    full_text = punctuate(sub.segments)  # 带标点，与 markdown 纯文本一致
    preview = full_text[:80] + ("…" if len(full_text) > 80 else "")

    return PipelineResult(
        title=info.title,
        bvid=info.bvid,
        level=sub.level,
        source_label=LEVEL_LABEL.get(sub.level, sub.level),
        segment_count=len(sub.segments),
        file_path=str(path),
        preview=preview,
        text=full_text,
        attempts=attempts,
    )
