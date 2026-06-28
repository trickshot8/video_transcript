"""Multi-source transcript pipeline: platform subtitles -> API ASR -> local Whisper."""
from __future__ import annotations

import logging
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import config
from pipeline import asr, bilibili, catalog, perf, summarize, youtube
from pipeline.markdown import label, punctuate, save_markdown
from pipeline.models import SubtitleResult, VideoInfo

log = logging.getLogger("transcript")


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


@dataclass
class PipelineResult:
    title: str
    video_id: str
    level: str
    source_label: str
    segment_count: int
    file_path: str
    preview: str
    text: str = ""
    summary: str = ""
    filename: str = ""
    duplicate: bool = False
    attempts: list[str] = field(default_factory=list)


def _meta_header(title: str, owner: str, source: str, url: str, source_label: str) -> str:
    owner_label = "UP主" if source == "bilibili" else "频道"
    lines = [f"《{title}》"]
    if owner:
        lines.append(f"{owner_label}：{owner}")
    lines.append(f"来源：{url}")
    lines.append(f"字幕来源：{source_label}")
    return "\n".join(lines) + "\n\n"


def _with_meta(info: VideoInfo, source_label: str, transcript: str) -> str:
    return _meta_header(info.title, info.owner, info.source, info.url, source_label) + transcript


def _read_transcript(path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return content.split("## 纯文本", 1)[1].strip() if "## 纯文本" in content else ""


def _dedup(video_id: str, force: bool, force_whisper: bool) -> Optional[PipelineResult]:
    if force or force_whisper:
        return None
    entry = catalog.get(video_id)
    if not entry:
        return None
    path = config.OUTPUT_DIR / (entry.get("folder") or "") / entry["filename"]
    if not path.exists():
        return None

    transcript = _read_transcript(path)
    text = _meta_header(
        entry.get("title", ""),
        entry.get("owner", ""),
        entry.get("source", ""),
        entry.get("url", ""),
        entry.get("source_label", ""),
    ) + transcript
    return PipelineResult(
        title=entry.get("title", ""),
        video_id=video_id,
        level=entry.get("level", ""),
        source_label=entry.get("source_label", ""),
        segment_count=entry.get("segment_count", 0),
        file_path=str(path),
        filename=entry["filename"],
        summary=entry.get("summary", ""),
        preview=entry.get("preview", transcript[:80]),
        text=text,
        duplicate=True,
        attempts=["命中目录，返回已有结果"],
    )


def _route(raw_url: str):
    if youtube.is_youtube(raw_url):
        vid = youtube.extract_id(raw_url)
        return vid, None, youtube.get_video_info, youtube.fetch_subtitle
    vid, page = bilibili.resolve_url(raw_url)
    return (
        vid,
        page,
        lambda v: bilibili.get_video_info(v, page),
        bilibili.fetch_bilibili_subtitle,
    )


def run(
    raw_url: str,
    allow_api_asr: bool = True,
    allow_local_whisper: bool = True,
    force_whisper: bool = False,
    force: bool = False,
) -> PipelineResult:
    pipeline_started = time.perf_counter()
    timings: dict[str, int] = {}
    attempts: list[str] = []
    vid, page, get_info, fetch = _route(raw_url)

    hit = _dedup(vid, force, force_whisper)
    if hit:
        log.info("命中目录(早)，跳过取信息: %s", vid)
        return hit

    stage_started = time.perf_counter()
    info: VideoInfo = get_info(vid)
    timings["video_info"] = _elapsed_ms(stage_started)
    log.info("视频[%s]: %s (%s)", info.source, info.title, info.video_id)

    hit = _dedup(info.video_id, force, force_whisper)
    if hit:
        log.info("命中目录，返回已有结果: %s", info.video_id)
        return hit

    sub: Optional[SubtitleResult] = None

    if force_whisper:
        log.info("强制本地 Whisper 转写…")
        stage_started = time.perf_counter()
        sub = asr.transcribe_local(info, page)
        timings["local_whisper_total"] = _elapsed_ms(stage_started)
        attempts.append("强制本地Whisper转写")
    else:
        stage_started = time.perf_counter()
        try:
            sub = fetch(info)
            attempts.append(
                f"{info.source}{sub.level}字幕命中" if sub else f"{info.source}无可用字幕"
            )
        except Exception as e:  # noqa: BLE001
            attempts.append(f"字幕抓取异常: {e}")
            log.warning("字幕抓取异常: %s", e)
        finally:
            timings["platform_subtitle"] = _elapsed_ms(stage_started)

        if sub is None and allow_api_asr:
            if asr.api_available():
                stage_started = time.perf_counter()
                try:
                    log.info("降级到云端 ASR API 转写…")
                    sub = asr.transcribe_api(info, page)
                    attempts.append("SenseVoiceSmall API转写完成")
                except Exception as e:  # noqa: BLE001
                    attempts.append(f"ASR API转写异常: {e}")
                    log.warning("ASR API转写异常: %s", e)
                finally:
                    timings["api_asr_total"] = _elapsed_ms(stage_started)
            else:
                attempts.append("ASR API未配置")

        if sub is None and allow_local_whisper:
            log.info("降级到本地 Whisper 转写…")
            stage_started = time.perf_counter()
            sub = asr.transcribe_local(info, page)
            timings["local_whisper_total"] = _elapsed_ms(stage_started)
            attempts.append("本地Whisper转写完成")

    if sub is None:
        if not allow_api_asr and not allow_local_whisper:
            raise RuntimeError("该视频无可用字幕，且所有 ASR fallback 都已关闭")
        raise RuntimeError("未能获取字幕，所有 fallback 均失败。尝试记录: " + "; ".join(attempts))

    timings.update(sub.timings_ms)
    stage_started = time.perf_counter()
    transcript = punctuate(sub.segments)
    timings["transcript_format"] = _elapsed_ms(stage_started)
    preview = transcript[:80] + ("…" if len(transcript) > 80 else "")
    source_label = label(info.source, sub.level)
    full_text = _with_meta(info, source_label, transcript)

    stage_started = time.perf_counter()
    summary = summarize.summarize(info.title, transcript) or ""
    timings["summary"] = _elapsed_ms(stage_started)
    if summary:
        attempts.append("已生成摘要")

    stage_started = time.perf_counter()
    path = save_markdown(info, sub, summary=summary)
    timings["markdown_save"] = _elapsed_ms(stage_started)
    total_to_saved_ms = _elapsed_ms(pipeline_started)

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
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    # 性能记录：非必须，独立追加到 _perf.jsonl，不进 catalog（避免索引膨胀/全量重写）
    transcript_model = (
        config.ASR_MODEL if sub.level == "api"
        else config.WHISPER_MODEL if sub.level == "whisper"
        else None
    )
    perf.log_run({
        "video_id": info.video_id,
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "host_label": config.PERF_HOST_LABEL or platform.machine() or "unknown",
        "machine": platform.machine(),
        "python": platform.python_version(),
        "source_level": sub.level,
        "video_duration_sec": info.duration,
        "transcript_chars": len(transcript),
        "summary_chars": len(summary),
        "models": {
            "summary": config.SUMMARY_MODEL if summary else None,
            "transcript": transcript_model,
        },
        "backends": {
            "summary": config.SUMMARY_BASE_URL if summary else None,
            "transcript": (
                config.ASR_BASE_URL if sub.level == "api"
                else "local" if sub.level == "whisper"
                else info.source
            ),
        },
        "summary_prompt": summarize.PROMPT_VERSION if summary else None,
        "stages_ms": timings,
        "total_to_saved_ms": total_to_saved_ms,
    })
    log.info(
        "耗时[%s]: total=%dms stages=%s",
        info.video_id,
        total_to_saved_ms,
        timings,
    )

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
