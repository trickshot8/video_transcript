"""Offline smoke tests for parsing and rendering."""
from pathlib import Path

from pipeline import asr, bilibili, transcript
from pipeline.markdown import _safe_filename, _ts, render_markdown
from pipeline.models import Segment, SubtitleResult, VideoInfo


def test_resolve_url():
    cases = [
        ("https://www.bilibili.com/video/BV1xx411c7mD", ("BV1xx411c7mD", None)),
        ("https://www.bilibili.com/video/BV1xx411c7mD?p=3", ("BV1xx411c7mD", 3)),
        ("看看这个 BV1xx411c7mD 不错", ("BV1xx411c7mD", None)),
        ("https://www.bilibili.com/video/av170001", ("av170001", None)),
        ("【标题】一大段简介… https://www.bilibili.com/video/BV1xx411c7mD?p=2&t=5 来自哔哩哔哩",
         ("BV1xx411c7mD", 2)),
        ("看这个 https://m.bilibili.com/video/BV1xx411c7mD 不错", ("BV1xx411c7mD", None)),
    ]
    for inp, expected in cases:
        got = bilibili.resolve_url(inp)
        assert got == expected, f"{inp!r} -> {got}, 期望 {expected}"
    print("resolve_url ✅")


def test_ts():
    assert _ts(5) == "00:05"
    assert _ts(65) == "01:05"
    assert _ts(3661) == "01:01:01"
    print("_ts ✅")


def test_safe_filename():
    assert _safe_filename('a/b:c*d?"<>|') == "a_b_c_d_____"
    assert _safe_filename("") == "untitled"
    print("_safe_filename ✅")


def test_render():
    info = VideoInfo(
        video_id="BV1xx411c7mD",
        source="bilibili",
        url="https://www.bilibili.com/video/BV1xx411c7mD",
        cid=123,
        title="测试视频",
        page_title="第一P",
        owner="某UP",
        duration=120,
    )
    sub = SubtitleResult(
        segments=[Segment(0, 2, "大家好"), Segment(2, 5, "今天我们聊聊")],
        level="ai",
        lan_doc="中文(自动生成)",
    )
    md = render_markdown(info, sub)
    assert "# 测试视频" in md
    assert "B站AI字幕" in md
    assert "`[00:00]` 大家好" in md
    assert "大家好，今天我们聊聊" in md
    print("render_markdown ✅")


def test_asr_payload_parser():
    payload = {
        "text": "大家好 今天我们聊聊",
        "segments": [
            {"start": 0, "end": 1.2, "text": "大家好"},
            {"start": "1.2", "end": "3.6", "text": "今天我们聊聊"},
        ],
    }
    segs = asr._segments_from_transcription_payload(payload, duration_hint=10)
    assert len(segs) == 2
    assert segs[0].text == "大家好"
    assert segs[1].start == 1.2

    fallback = asr._segments_from_transcription_payload({"text": "整段文本"}, duration_hint=9)
    assert len(fallback) == 1
    assert fallback[0].end == 9
    print("asr_payload_parser ✅")


def test_processing_metrics():
    catalog_saved: dict = {}
    perf_logged: dict = {}
    originals = (
        bilibili.get_video_info,
        bilibili.fetch_bilibili_subtitle,
        transcript.summarize.summarize,
        transcript.save_markdown,
        transcript.catalog.get,
        transcript.catalog.upsert,
        transcript.perf.log_run,
    )
    try:
        bilibili.get_video_info = lambda video_id, page=None: VideoInfo(
            video_id=video_id,
            source="bilibili",
            title="性能测试",
            url=f"https://www.bilibili.com/video/{video_id}",
            duration=60,
        )
        bilibili.fetch_bilibili_subtitle = lambda info: SubtitleResult(
            segments=[Segment(0, 10, "测试字幕")],
            level="ai",
            lan_doc="中文(自动生成)",
        )
        transcript.summarize.summarize = lambda title, text: "测试摘要"
        transcript.save_markdown = lambda info, sub, summary="": Path("test.md")
        transcript.catalog.get = lambda video_id: None
        transcript.catalog.upsert = lambda entry: catalog_saved.update(entry)
        transcript.perf.log_run = lambda entry: perf_logged.update(entry)

        result = transcript.run("BV1xx411c7mD", force=True)

        # 性能记录进了独立的 perf 日志，不进 catalog
        assert "processing_runs" not in catalog_saved
        assert perf_logged["source_level"] == "ai"
        assert perf_logged["video_duration_sec"] == 60
        assert perf_logged["transcript_chars"] > 0
        assert perf_logged["backends"]["summary"]
        assert perf_logged["summary_prompt"] == transcript.summarize.PROMPT_VERSION
        assert "video_info" in perf_logged["stages_ms"]
        assert "platform_subtitle" in perf_logged["stages_ms"]
        assert "summary" in perf_logged["stages_ms"]
        assert "markdown_save" in perf_logged["stages_ms"]
        assert not hasattr(result, "timings_ms")
    finally:
        (
            bilibili.get_video_info,
            bilibili.fetch_bilibili_subtitle,
            transcript.summarize.summarize,
            transcript.save_markdown,
            transcript.catalog.get,
            transcript.catalog.upsert,
            transcript.perf.log_run,
        ) = originals
    print("processing_metrics ✅")

if __name__ == "__main__":
    test_resolve_url()
    test_ts()
    test_safe_filename()
    test_render()
    test_asr_payload_parser()
    test_processing_metrics()
    print("\n全部冒烟测试通过 ✅")
