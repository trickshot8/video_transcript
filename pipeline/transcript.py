"""三级 fallback 编排：B站CC字幕 -> B站AI字幕 -> 本地Whisper。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import config
from pipeline import asr, bilibili, catalog, summarize
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
    text: str = ""           # 完整字幕(带 metadata 头 + 标点)，给快捷指令复制用
    summary: str = ""        # LLM 摘要（可能为空）
    filename: str = ""       # md 文件名(basename)，给文件整理接口引用
    duplicate: bool = False  # 命中目录、直接返回的已有结果
    attempts: list[str] = field(default_factory=list)


def _video_url(info: bilibili.VideoInfo) -> str:
    return f"https://www.bilibili.com/video/{info.bvid}"


def _with_meta(info: bilibili.VideoInfo, source_label: str, transcript: str) -> str:
    """给全文加上 metadata 头，喂 LLM 时自带上下文。"""
    lines = [f"《{info.title}》"]
    if info.owner:
        lines.append(f"UP主：{info.owner}")
    lines.append(f"来源：{_video_url(info)}")
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
        bvid=video_id,
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


def run(raw_url: str, allow_whisper: bool = True,
        force_whisper: bool = False, force: bool = False) -> PipelineResult:
    attempts: list[str] = []
    vid, page = bilibili.resolve_url(raw_url)

    # 早去重：resolve 已拿到 BV 号，直接查本地目录，命中就返回——**不调 view API、不联网**
    hit = _dedup(vid, force, force_whisper)
    if hit:
        log.info("命中目录(早)，跳过取信息: %s", vid)
        return hit

    info = bilibili.get_video_info(vid, page)
    log.info("视频: %s (%s) cid=%s", info.title, info.bvid, info.cid)

    # 兜底再查一次：处理 av 号等 vid != 规范 bvid 的情况
    hit = _dedup(info.bvid, force, force_whisper)
    if hit:
        log.info("命中目录，返回已有: %s", info.bvid)
        return hit

    sub: Optional[bilibili.SubtitleResult] = None

    # force_whisper：跳过B站字幕，直接本地转写（用于对比/测试）
    if force_whisper:
        log.info("强制本地 Whisper 转写…")
        sub = asr.transcribe_local(info, page)
        attempts.append("强制本地Whisper转写")
    else:
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

    transcript = punctuate(sub.segments)            # 纯字幕(带标点)
    preview = transcript[:80] + ("…" if len(transcript) > 80 else "")
    source_label = LEVEL_LABEL.get(sub.level, sub.level)
    full_text = _with_meta(info, source_label, transcript)  # 给复制/LLM 用，带 metadata 头

    # 摘要（失败返回空串，不影响主流程）
    summary = summarize.summarize(info.title, transcript) or ""
    if summary:
        attempts.append("已生成摘要")

    path = save_markdown(info, sub, summary=summary)

    # 写入目录索引（去重 + 检索的单一数据源）
    catalog.upsert({
        "video_id": info.bvid,
        "title": info.title,
        "owner": info.owner,
        "source": "bilibili",
        "url": _video_url(info),
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
        bvid=info.bvid,
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
