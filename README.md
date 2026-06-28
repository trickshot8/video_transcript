# video_transcript — 视频字幕提取 + AI 摘要 + 文件归档

> 在 B站 / YouTube App 里点一下「分享」，几秒后手机弹出 AI 摘要、完整字幕进了剪贴板——
> 看一眼摘要就能决定这条笔记要保留、删除还是归类，全程不用碰电脑。

视频看完就忘、字幕东一份西一份找不到？这个项目把"看视频记笔记"全自动化了：

- 📱 **零摩擦**：手机分享链接即触发，弹通知一步选保留/删除/归类
- 🎯 **多级兜底**：人工字幕 → 平台自动字幕 → 云端语音转写 → 本地 Whisper，尽量都能拿到文字
- 🌐 **B站 + YouTube 通用**：同一套快捷指令，服务端自动识别平台
- 🧠 **AI 摘要**：DeepSeek 生成结构化中文摘要，区分事实/观点/预测，一眼判断值不值得细看
- 🗂️ **自动整理**：同一视频不重复处理，文件可按文件夹归类，全文带 metadata 方便丢给其它 LLM 分析
- 🐳 **24/7 常驻**：Docker 部署到树莓派，开机自启，几乎零功耗、零运维

适合：经常刷 B站/YouTube 知识类视频，想要可检索的文字笔记，又懒得手动复制粘贴的人。

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
| POST | `/jobs` | 提交任务，body `{"url": "...", "sync": false, "force": false}`，返回 `job_id` |
| GET  | `/jobs/<job_id>` | 查询状态与结果（含 `message`/`summary`/`text`/`filename`/`duplicate`） |
| GET  | `/files/folders` | 列出输出目录下已有的分类文件夹（给整理菜单用） |
| POST | `/files/action` | 整理 md：`{"filename","action":"keep\|delete\|favorite\|tag","tag"?}` |

`POST /jobs` 加 `"sync": true` 会阻塞直到处理完成再返回；加 `"force": true` 会忽略目录去重，强制重新处理。

如果 `.env` 设了 `API_TOKEN`，请求需带 `?token=xxx` 或 header `X-Token`。

## 输出

markdown 落在 `OUTPUT_DIR`，包含：

- 视频标题 / 来源 / UP主或频道
- 带时间戳字幕（云 ASR 单段结果无逐句时间戳，自动跳过该区块）
- 纯文本字幕（按停顿自动补标点）
- 可选摘要（DeepSeek 生成，置顶显示）

### 目录索引与去重

`OUTPUT_DIR/_catalog.json` 是一个纯索引文件：记录每个视频的元数据、摘要和文件名指针，
**不存全文**（全文只在各自的 `.md` 里，避免索引随视频数膨胀）。处理前会先查这个索引，
命中且文件还在就直接返回已有结果（不再抓字幕、不再调摘要 API），响应里 `duplicate: true`。
想强制重跑用 `force`（`cli.py --force` 或请求体 `"force": true`）。
整理（移动/删除）文件时会同步更新索引。

### 文件整理（保留 / 删除 / 归类）

`/files/action` 把 md 文件做三类处理：`delete`（删除）、`keep`（不动）、`tag`（移进
`<tag>/` 子文件夹，不存在会自动创建；"收藏"也只是叫"收藏"的子文件夹）。
`/files/folders` 列出已有子文件夹，方便客户端做"选已有 / 新建"的归类菜单
（具体快捷指令搭法见 [ios/shortcut_setup.md](ios/shortcut_setup.md)）。

### 性能日志（可选，非必须）

每次实际处理（非去重命中）会在 `OUTPUT_DIR/_perf.jsonl` 追加一行 JSON，记录各阶段耗时、
模型、后端、设备架构和输入规模——纯日志性质，与 `_catalog.json` 完全分离，不影响索引体积。
需要比较不同设备时，可在 `.env` 设置易读标签：

```env
PERF_HOST_LABEL=pi5
```

## YouTube 支持

链接里含 `youtube.com` / `youtu.be` 会自动路由到 YouTube 抓取逻辑，无需额外配置；
iOS 快捷指令完全不用区分平台，同一套流程两边都能用。字幕优先级：

1. 人工字幕（中文优先，否则视频原语言）
2. 自动字幕（**只取原语言**，不强求自动翻译成中文——YouTube 对翻译字幕限流很狠，
   原生语言字幕能稳定下载；摘要始终由 DeepSeek 生成中文，与字幕本身的语言无关）
3. 云 ASR / 本地 Whisper 兜底（同 B站）

如果某个视频仍频繁 429，可在项目根目录建 `cookies/youtube.txt`
（Netscape 格式，用浏览器扩展如「Get cookies.txt LOCALLY」登录后导出），
`.env` 设 `YOUTUBE_COOKIES` 指向它即可（Docker 部署时 compose 已把 `./cookies` 挂进容器）。

## iOS 快捷指令

见 [ios/shortcut_setup.md](ios/shortcut_setup.md)。
