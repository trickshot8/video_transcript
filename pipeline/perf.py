"""Optional performance log: append-only JSONL, separate from the catalog.

Not essential to the product — purely for comparing stage timings across
hardware/models. Kept out of _catalog.json so the index stays lean and isn't
rewritten in full on every run just to append a timing record.
"""
from __future__ import annotations

import json
import logging
import threading

import config

log = logging.getLogger("perf")

_PATH = config.OUTPUT_DIR / "_perf.jsonl"
_lock = threading.Lock()


def log_run(entry: dict) -> None:
    """Append one processing-run record. Best-effort: never raises."""
    try:
        with _lock:
            with _PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("写入性能日志失败: %s", e)
