"""命令行入口，便于本地测试整条 pipeline：

  python cli.py "https://www.bilibili.com/video/BVxxxx"
  python cli.py --no-whisper "BVxxxx"          # 只试 B站字幕，不跑本地转写
  python cli.py --force-whisper --model medium "BVxxxx"  # 强制用 medium 本地转写
"""
from __future__ import annotations

import argparse
import logging
import sys

import config
from pipeline.transcript import run


def main() -> int:
    parser = argparse.ArgumentParser(description="提取B站视频中文字幕为markdown")
    parser.add_argument("url", help="B站视频链接 / 短链 / BV号")
    parser.add_argument("--no-whisper", action="store_true",
                        help="禁用本地Whisper兜底（仅尝试B站字幕）")
    parser.add_argument("--force-whisper", action="store_true",
                        help="强制本地Whisper转写（跳过B站字幕，用于对比效果）")
    parser.add_argument("--model", default=None,
                        help="临时覆盖Whisper模型(tiny/base/small/medium/large-v3)，仅在跑Whisper时生效")
    parser.add_argument("--force", action="store_true",
                        help="忽略目录去重，强制重新处理（即使之前处理过）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.model:
        config.WHISPER_MODEL = args.model
        print(f"Whisper 模型覆盖为: {args.model}")

    try:
        result = run(args.url, allow_whisper=not args.no_whisper,
                     force_whisper=args.force_whisper, force=args.force)
    except Exception as e:  # noqa: BLE001
        print(f"❌ 失败: {e}", file=sys.stderr)
        return 1

    print(f"\n✅ 完成")
    print(f"标题   : {result.title}")
    print(f"来源   : {result.source_label}")
    print(f"条数   : {result.segment_count}")
    print(f"文件   : {result.file_path}")
    print(f"预览   : {result.preview}")
    print(f"过程   : {' -> '.join(result.attempts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
