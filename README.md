# video_transcript — B站视频中文字幕提取

iOS 手机复制 B 站视频链接 → 触发本机服务 → 三级 fallback 提取中文字幕 → 输出 markdown 并通知手机。

## 处理逻辑（三级 fallback）

1. **B站 CC / 人工字幕** — `player/v2` 接口里的人工字幕，质量最高。
2. **B站 AI 字幕** — UP 主开启的 AI 自动字幕（`lan=ai-zh`）。
3. **本地 Whisper** — 前两级都没有时，`yt-dlp` 下音频 → `faster-whisper` 本地转写。

> ⚠️ 现在 B 站字幕列表接口基本都需要登录态，**必须在 `.env` 里填 `BILIBILI_SESSDATA`**，否则前两级几乎总是空，会一路降级到 Whisper。

## 架构

```
iOS 快捷指令(分享菜单复制链接)
        │  HTTP POST /jobs  {url}
        ▼
Flask 服务 (server.py, 本机常驻)
        │
        ▼  pipeline.transcript.run()
  ┌─────────────────────────────┐
  │ 1 B站CC  2 B站AI  3 Whisper │
  └─────────────────────────────┘
        │
        ├─ 写 markdown 到 output/
        └─ 返回结果 JSON → 快捷指令轮询 → 弹本地通知
```

## 安装

需要：Python 3.10+、ffmpeg（已在 PATH）。

```bash
cd "E:/Codex Project/Home AI Agent/video_transcript"
python -m venv .venv
.venv\Scripts\activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env          # 然后编辑 .env，至少填 BILIBILI_SESSDATA
```

## 用法

### 命令行（先验证 pipeline）

```bash
python cli.py "https://www.bilibili.com/video/BVxxxxxxxxxx"
python cli.py --no-whisper "BVxxxxxxxxxx"   # 只测B站字幕
```

### 服务

```bash
python server.py
```

接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/health` | 健康检查 |
| POST | `/jobs` | 提交任务，body `{"url": "...", "sync": false}`，返回 `job_id`（含 `summary`/`text`/`filename`） |
| GET  | `/jobs/<job_id>` | 查询状态/结果 |
| POST | `/files/action` | 整理 md：body `{"filename","action":"keep\|delete\|favorite\|tag","tag"?}` |

`POST /jobs` 加 `"sync": true` 会阻塞直到完成再返回（短视频方便，长视频可能超时）。
默认异步：先返回 `job_id`，再轮询 `/jobs/<id>` 直到 `status=done`。

若 `.env` 设了 `API_TOKEN`，请求需带 `?token=xxx` 或 header `X-Token`。

### iOS 快捷指令

见 [ios/shortcut_setup.md](ios/shortcut_setup.md)。

## 输出

markdown 落在 `output/`，包含：标题、来源、带时间戳字幕、纯文本（方便丢给 LLM 总结）。

## 让手机能访问本机

`HOST=0.0.0.0` 后，手机与 PC 同一局域网即可用 PC 内网 IP 访问；不在同一网络推荐装
[Tailscale](https://tailscale.com/) 组虚拟内网，用 Tailscale IP 即可随时随地触发。
