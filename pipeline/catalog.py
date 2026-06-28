"""字幕目录索引（单一 JSON）。

记录所有已处理视频的元数据 + 摘要 + 全文，作为**去重和检索的唯一数据源**——
不必再遍历扫描一堆 .md 文件。每次保存字幕、以及整理(移动/删除)文件时同步更新。

文件：<OUTPUT_DIR>/_catalog.json
结构：{"videos": {"<video_id>": { ...entry... }}}
"""
from __future__ import annotations

import json
import threading

import config

_PATH = config.OUTPUT_DIR / "_catalog.json"
_lock = threading.Lock()


def _load() -> dict:
    if _PATH.exists():
        try:
            data = json.loads(_PATH.read_text(encoding="utf-8"))
            data.setdefault("videos", {})
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"videos": {}}


def _write(data: dict) -> None:
    tmp = _PATH.with_name(_PATH.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_PATH)


def get(video_id: str) -> dict | None:
    with _lock:
        return _load()["videos"].get(video_id)


def upsert(entry: dict) -> None:
    """新增/更新一条，entry 必须含 video_id。"""
    with _lock:
        data = _load()
        data["videos"][entry["video_id"]] = entry
        _write(data)


def update_folder(filename: str, folder: str) -> None:
    """文件被整理移动后，更新对应条目的 folder。"""
    with _lock:
        data = _load()
        for e in data["videos"].values():
            if e.get("filename") == filename:
                e["folder"] = folder
        _write(data)


def remove_by_filename(filename: str) -> None:
    """文件被删除后，移除对应条目。"""
    with _lock:
        data = _load()
        gone = [vid for vid, e in data["videos"].items()
                if e.get("filename") == filename]
        for vid in gone:
            del data["videos"][vid]
        if gone:
            _write(data)
