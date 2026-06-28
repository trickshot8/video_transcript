"""CLI entry for locally testing the transcript pipeline."""
from __future__ import annotations

import argparse
import logging
import sys

import config
from pipeline.transcript import run


def main() -> int:
    parser = argparse.ArgumentParser(description="提取 B站 / YouTube 视频字幕并保存为 markdown")
    parser.add_argument("url", help="视频链接 / BV号 / YouTube URL")
    parser.add_argument("--no-whisper", action="store_true",
                        help="禁用本地 Whisper 兜底（仍可使用云端 ASR）")
    parser.add_argument("--no-api-asr", action="store_true",
                        help="禁用 SenseVoiceSmall API 兜底")
    parser.add_argument("--force-whisper", action="store_true",
                        help="强制本地 Whisper 转写（跳过平台字幕和云端 ASR）")
    parser.add_argument("--model", default=None,
                        help="临时覆盖 Whisper 模型 (tiny/base/small/medium/large-v3)")
    parser.add_argument("--force", action="store_true",
                        help="忽略目录去重，强制重新处理")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.model:
        config.WHISPER_MODEL = args.model
        print(f"Whisper 模型覆盖为: {args.model}")

    try:
        result = run(
            args.url,
            allow_api_asr=not args.no_api_asr,
            allow_local_whisper=not args.no_whisper,
            force_whisper=args.force_whisper,
            force=args.force,
        )
    except Exception as e:  # noqa: BLE001
        print(f"❌ 失败: {e}", file=sys.stderr)
        return 1

    print("\n✅ 完成")
    print(f"标题   : {result.title}")
    print(f"来源   : {result.source_label}")
    print(f"条数   : {result.segment_count}")
    print(f"文件   : {result.file_path}")
    print(f"预览   : {result.preview}")
    print(f"过程   : {' -> '.join(result.attempts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
