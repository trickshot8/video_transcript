"""Flask 服务：接收 iOS 快捷指令发来的 B站链接，异步跑 pipeline。

接口：
  GET  /health                  健康检查
  POST /jobs                    提交任务 {"url": "...", "token": "..."}；可加 "sync": true 同步等待
  GET  /jobs/<job_id>           查询任务状态与结果
  POST /files/action            整理 md 文件：保留/删除/收藏/打标签

iOS 快捷指令推荐用法见 ios/shortcut_setup.md。
"""
from __future__ import annotations

import logging
import re
import threading
import uuid
from typing import Any

from flask import Flask, jsonify, request

import config
from pipeline.transcript import run as run_pipeline

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("server")

app = Flask(__name__)

# 简单的内存任务表（重启即清空，够个人用）
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _check_token(req) -> bool:
    if not config.API_TOKEN:
        return True
    token = (req.args.get("token")
             or req.headers.get("X-Token")
             or (req.json.get("token") if req.is_json else None))
    return token == config.API_TOKEN


def _set(job_id: str, **fields):
    with _lock:
        _jobs.setdefault(job_id, {})
        _jobs[job_id].update(fields)


def _process(job_id: str, url: str):
    _set(job_id, status="processing")
    try:
        result = run_pipeline(url, allow_whisper=config.ENABLE_WHISPER)
        # 按可靠性给每级字幕配徽标，一眼可辨用了哪个 fallback
        badge = {"cc": "🟢", "ai": "🔵", "whisper": "🟡"}.get(result.level, "✅")
        head = f"{badge} {result.source_label} · {result.segment_count}条\n《{result.title}》"
        # 通知正文：有摘要就把摘要带上，扫一眼判断价值
        msg = head + (f"\n\n{result.summary}" if result.summary else "")
        # message/text/summary/filename 都放顶层，方便快捷指令直接取用
        _set(job_id, status="done", message=msg, text=result.text,
             summary=result.summary, filename=result.filename, result={
                "title": result.title,
                "bvid": result.bvid,
                "level": result.level,
                "source": result.source_label,
                "segments": result.segment_count,
                "file": result.file_path,
                "filename": result.filename,
                "preview": result.preview,
                "summary": result.summary,
                "text": result.text,
                "attempts": result.attempts,
                "message": msg,
            })
        log.info("job %s 完成: %s", job_id, result.file_path)
    except Exception as e:  # noqa: BLE001
        log.exception("job %s 失败", job_id)
        msg = f"❌ 处理失败: {e}"
        _set(job_id, status="error", message=msg,
             result={"message": msg, "error": str(e)})


@app.get("/health")
def health():
    return jsonify(ok=True, jobs=len(_jobs))


@app.post("/jobs")
def create_job():
    if not _check_token(request):
        return jsonify(error="unauthorized"), 401
    payload = request.get_json(silent=True) or request.form
    url = (payload.get("url") or request.args.get("url") or "").strip()
    if not url:
        return jsonify(error="缺少 url 参数"), 400
    sync = str(payload.get("sync", request.args.get("sync", ""))).lower() in ("1", "true", "yes")

    job_id = uuid.uuid4().hex[:12]
    _set(job_id, status="queued", url=url)

    if sync:
        _process(job_id, url)
        return jsonify(job_id=job_id, **_jobs[job_id])

    threading.Thread(target=_process, args=(job_id, url), daemon=True).start()
    return jsonify(job_id=job_id, status="queued"), 202


@app.get("/jobs/<job_id>")
def get_job(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify(error="job not found"), 404
    return jsonify(job_id=job_id, **job)


_BAD_NAME = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _safe_subdir(name: str) -> str:
    name = _BAD_NAME.sub("_", name).strip().strip(".")
    return name[:40] or "未命名"


@app.post("/files/action")
def file_action():
    """整理 md 文件。body: {filename, action: keep|delete|favorite|tag, tag?}"""
    if not _check_token(request):
        return jsonify(error="unauthorized"), 401
    payload = request.get_json(silent=True) or request.form
    filename = (payload.get("filename") or "").strip()
    action = (payload.get("action") or "").strip().lower()
    tag = (payload.get("tag") or "").strip()

    if not filename:
        return jsonify(error="缺少 filename"), 400
    # 安全：只允许纯 basename，禁止路径穿越
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify(error="非法文件名"), 400
    out = config.OUTPUT_DIR.resolve()
    src = (out / filename)
    if src.resolve().parent != out:
        return jsonify(error="文件不在输出目录内"), 400
    if not src.is_file():
        return jsonify(error="文件不存在"), 404

    if action == "keep":
        return jsonify(ok=True, message="✅ 已保留")
    if action == "delete":
        src.unlink()
        log.info("已删除 %s", src.name)
        return jsonify(ok=True, message="🗑 已删除")
    if action == "favorite":
        dest_dir = out / "收藏"
    elif action == "tag":
        if not tag:
            return jsonify(error="tag 操作需要 tag 参数"), 400
        dest_dir = out / _safe_subdir(tag)
    else:
        return jsonify(error=f"未知 action: {action}"), 400

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    src.replace(dest)
    log.info("已移动 %s -> %s/", src.name, dest_dir.name)
    return jsonify(ok=True, message=f"📁 已移动到「{dest_dir.name}」", path=str(dest))


if __name__ == "__main__":
    log.info("启动 video_transcript 服务于 %s:%s", config.HOST, config.PORT)
    app.run(host=config.HOST, port=config.PORT, threaded=True)
