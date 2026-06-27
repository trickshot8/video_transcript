"""命令行入口，便于本地测试整条 pipeline：

  python cli.py "https://www.bilibili.com/video/BVxxxx"
  python cli.py --no-whisper "BVxxxx"   # 只试 B站字幕，不跑本地转写
"""
from __future__ import annotations

import argparse
import logging
import sys

from pipeline.transcript import run


def main() -> int:
    parser = argparse.ArgumentParser(description="提取B站视频中文字幕为markdown")
    parser.add_argument("url", help="B站视频链接 / 短链 / BV号")
    parser.add_argument("--no-whisper", action="store_true",
                        help="禁用本地Whisper兜底（仅尝试B站字幕）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        result = run(args.url, allow_whisper=not args.no_whisper)
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
