# video_transcript — 多平台视频字幕提取

iOS 手机复制 B站或 YouTube 视频链接 → 触发本机服务 → 多级 fallback 提取字幕 → 输出 markdown 并通知手机。

## 处理逻辑（四级 fallback）

1. **B站 CC / 人工字幕** — `player/v2` 接口里的人工字幕，质量最高。
2. **平台自动字幕** — B站 AI 字幕 / YouTube 自动字幕。
3. **SenseVoiceSmall API** — 平台没有字幕时，`yt-dlp` 下载音频并上传到 OpenAI 兼容 `/audio/transcriptions`。
4. **本地 Whisper** — 云端 ASR 不可用或失败时，再回退到 `faster-whisper` 本地转写。

> ⚠️ 现在 B站字幕列表接口基本都需要登录态，**必须在 `.env` 里填 `BILIBILI_SESSDATA`**，否则前两级很容易拿不到字幕。

## 架构

```text
iOS 快捷指令(分享菜单复制链接)
        │  HTTP POST /jobs  {url}
        ▼
Flask 服务 (server.py)
        │
        ▼  pipeline.transcript.run()
  ┌──────────────────────────────────────┐
  │ 1 平台字幕  2 SenseVoiceSmall API  3 本地 Whisper │
  └──────────────────────────────────────┘
        │
        ├─ 写 markdown 到 output/
        └─ 返回结果 JSON 给快捷指令 / 客户端
```

## 安装

需要：Python 3.10+、ffmpeg（已在 PATH）。

```bash
cd "E:/Codex Project/Home AI Agent/video_transcript"
python -m venv .venv
.venv\Scripts\activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env
```

如果你要启用 SenseVoiceSmall fallback，还需要在 `.env` 里填写：

```env
ASR_ENABLED=true
ASR_API_KEY=your_key_here
ASR_BASE_URL=https://api.siliconflow.cn/v1
ASR_MODEL=FunAudioLLM/SenseVoiceSmall
```

## 用法

### 命令行

```bash
python cli.py "https://www.bilibili.com/video/BVxxxxxxxxxx"
python cli.py --no-whisper "BVxxxxxxxxxx"   # 禁用本地 Whisper，仍允许云端 ASR
python cli.py --no-api-asr "BVxxxxxxxxxx"   # 跳过云端 ASR，只用平台字幕/本地 Whisper
python cli.py --no-api-asr --no-whisper "BVxxxxxxxxxx"   # 只测平台字幕
python cli.py --force-whisper --model medium "BVxxxxxxxxxx"
```

### 服务

```bash
python server.py
```

接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/health` | 健康检查 |
| POST | `/jobs` | 提交任务，body `{"url": "...", "sync": false}` |
| GET  | `/jobs/<job_id>` | 查询状态与结果 |
| POST | `/files/action` | 整理 md 文件 |

如果 `.env` 设了 `API_TOKEN`，请求需带 `?token=xxx` 或 header `X-Token`。

## 输出

markdown 落在 `output/`，包含：

- 视频标题 / 来源
- 带时间戳字幕
- 纯文本字幕
- 可选摘要

## iOS 快捷指令

见 [ios/shortcut_setup.md](ios/shortcut_setup.md)。
