"""多来源编排：B站 / YouTube → CC字幕 → 自动字幕 → 本地Whisper。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import config
from pipeline import asr, bilibili, catalog, summarize, youtube
from pipeline.markdown import label, punctuate, save_markdown
from pipeline.models import SubtitleResult, VideoInfo

log = logging.getLogger("transcript")


@dataclass
class PipelineResult:
    title: str
    video_id: str
    level: str               # cc / ai / whisper
    source_label: str
    segment_count: int
    file_path: str
    preview: str             # 纯文本前若干字，给通知用
    text: str = ""           # 完整字幕(带 metadata 头 + 标点)，给快捷指令复制用
    summary: str = ""        # LLM 摘要（可能为空）
    filename: str = ""       # md 文件名(basename)，给文件整理接口引用
    duplicate: bool = False  # 命中目录、直接返回的已有结果
    attempts: list[str] = field(default_factory=list)


def _with_meta(info: VideoInfo, source_label: str, transcript: str) -> str:
    """给全文加上 metadata 头，喂 LLM 时自带上下文。"""
    owner_label = "UP主" if info.source == "bilibili" else "频道"
    lines = [f"《{info.title}》"]
    if info.owner:
        lines.append(f"{owner_label}：{info.owner}")
    lines.append(f"来源：{info.url}")
    lines.append(f"字幕来源：{source_label}")
    return "\n".join(lines) + "\n\n" + transcript


def _dedup(video_id: str, force: bool, force_whisper: bool) -> Optional[PipelineResult]:
    """查目录，命中且文件还在就返回已有结果；否则 None。纯本地、不联网。"""
    if force or force_whisper:
        return None
    entry = catalog.get(video_id)
    if not entry:
        return None
    path = config.OUTPUT_DIR / (entry.get("folder") or "") / entry["filename"]
    if not path.exists():
        return None
    text = entry.get("text", "")
    return PipelineResult(
        title=entry.get("title", ""),
        video_id=video_id,
        level=entry.get("level", ""),
        source_label=entry.get("source_label", ""),
        segment_count=entry.get("segment_count", 0),
        file_path=str(path),
        filename=entry["filename"],
        summary=entry.get("summary", ""),
        preview=entry.get("preview", text[:80]),
        text=text,
        duplicate=True,
        attempts=["命中目录，返回已有结果"],
    )


def _route(raw_url: str):
    """来源路由 → (video_id, page, get_info_fn, fetch_fn)。"""
    if youtube.is_youtube(raw_url):
        vid = youtube.extract_id(raw_url)
        return vid, None, youtube.get_video_info, youtube.fetch_subtitle
    vid, page = bilibili.resolve_url(raw_url)
    return (vid, page,
            lambda v: bilibili.get_video_info(v, page),
            bilibili.fetch_bilibili_subtitle)


def run(raw_url: str, allow_whisper: bool = True,
        force_whisper: bool = False, force: bool = False) -> PipelineResult:
    attempts: list[str] = []
    vid, page, get_info, fetch = _route(raw_url)

    # 早去重：用解析出的 ID 直接查本地目录，命中就返回——不取信息、尽量不联网
    hit = _dedup(vid, force, force_whisper)
    if hit:
        log.info("命中目录(早)，跳过取信息: %s", vid)
        return hit

    info: VideoInfo = get_info(vid)
    log.info("视频[%s]: %s (%s)", info.source, info.title, info.video_id)

    # 兜底再查一次：处理 ID 规范化后不同的情况（如 av 号）
    hit = _dedup(info.video_id, force, force_whisper)
    if hit:
        log.info("命中目录，返回已有: %s", info.video_id)
        return hit

    sub: Optional[SubtitleResult] = None

    if force_whisper:
        log.info("强制本地 Whisper 转写…")
        sub = asr.transcribe_local(info, page)
        attempts.append("强制本地Whisper转写")
    else:
        # 1+2 级：平台字幕（内部已优先人工，其次自动）
        try:
            sub = fetch(info)
            attempts.append(f"{info.source}{sub.level}字幕命中" if sub
                            else f"{info.source}无可用字幕")
        except Exception as e:  # noqa: BLE001  网络/接口异常都降级
            attempts.append(f"字幕抓取异常: {e}")
            log.warning("字幕抓取异常: %s", e)

        # 3 级：本地 whisper
        if sub is None and allow_whisper:
            log.info("降级到本地 Whisper 转写…")
            sub = asr.transcribe_local(info, page)
            attempts.append("本地Whisper转写完成")

    if sub is None:
        if not allow_whisper:
            raise RuntimeError("该视频无可用字幕，且本地Whisper转写已关闭")
        raise RuntimeError("未能获取字幕，本地转写也失败。尝试记录: " + "; ".join(attempts))

    transcript = punctuate(sub.segments)            # 纯字幕(带标点)
    preview = transcript[:80] + ("…" if len(transcript) > 80 else "")
    source_label = label(info.source, sub.level)
    full_text = _with_meta(info, source_label, transcript)  # 给复制/LLM 用，带 metadata 头

    # 摘要（失败返回空串，不影响主流程）
    summary = summarize.summarize(info.title, transcript) or ""
    if summary:
        attempts.append("已生成摘要")

    path = save_markdown(info, sub, summary=summary)

    # 写入目录索引（去重 + 检索的单一数据源）
    catalog.upsert({
        "video_id": info.video_id,
        "title": info.title,
        "owner": info.owner,
        "source": info.source,
        "url": info.url,
        "level": sub.level,
        "source_label": source_label,
        "segment_count": len(sub.segments),
        "filename": path.name,
        "folder": "",
        "summary": summary,
        "preview": preview,
        "text": full_text,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    return PipelineResult(
        title=info.title,
        video_id=info.video_id,
        level=sub.level,
        source_label=source_label,
        segment_count=len(sub.segments),
        file_path=str(path),
        filename=path.name,
        summary=summary,
        preview=preview,
        text=full_text,
        attempts=attempts,
    )
