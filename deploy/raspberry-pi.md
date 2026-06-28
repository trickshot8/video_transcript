# 树莓派部署（Docker + CasaOS）

架构：树莓派 = 主机，SSD 插在 Pi 上，CasaOS 把 SSD 上某文件夹共享到局域网
（Windows 映射为 `W:`，手机也连同一共享）。服务在同一台 Pi 上跑 Docker，
**直接写本地共享文件夹**——不需要 cifs/NAS 挂载。

精简模式：关闭本地 Whisper（弱算力设备跑不动），保留 B站/YouTube 平台字幕、
DeepSeek 摘要、云端 ASR 兜底（SenseVoiceSmall，免费、中文强）——这几个都只是
发 HTTP 请求，对 Pi 几乎零负担。

## 0. 前置

- 树莓派 **64位** 系统 + CasaOS（已自带 Docker）。
- 确认 Docker 可用：`docker version`、`sudo docker-compose version`。

## 1. 找到「被共享成 W: 的那个文件夹」的本地路径

W: 只是 Windows 看到的网络名，真正的物理目录在 Pi 的 SSD 上。本机 CasaOS 里
W: 根目录 = `/DATA/Documents`，所以之前在 W: 建的 `b站视频字幕` 文件夹对应：

```
/DATA/Documents/b站视频字幕
```

（里面已经有之前测试写入的 `.md` 文件。下文用它当 `OUTPUT_HOST_DIR`。）

## 2. 克隆项目到 /opt + 配置

仓库是 Public，clone 不需要任何登录：

```bash
sudo git clone https://github.com/trickshot8/video_transcript.git /opt/video_transcript
sudo chown -R $USER:$USER /opt/video_transcript   # 改属主，后续免 sudo
cd /opt/video_transcript

cp .env.example .env
nano .env
```

`.env` 里至少配：

```ini
BILIBILI_SESSDATA=你的SESSDATA
ENABLE_WHISPER=false
# 本地共享文件夹路径（W: 根=/DATA/Documents）
OUTPUT_HOST_DIR=/DATA/Documents/b站视频字幕

# 摘要（DeepSeek，platform.deepseek.com 申请，需实名）
DEEPSEEK_API_KEY=你的key

# 云 ASR 兜底（硅基流动 SenseVoiceSmall，siliconflow.cn 申请，免费）
ASR_API_KEY=你的key
```

> 容器内 `OUTPUT_DIR` 由 compose 强制为 `/data/subtitles`，并把 `OUTPUT_HOST_DIR`
> bind-mount 过去。写进去 = 直接落本地 SSD = 立刻出现在 W: 和手机共享里。
>
> 想用 YouTube cookies 缓解偶发 429：把 `cookies/youtube.txt` 放进项目根目录
> （compose 已挂载该目录），`.env` 设 `YOUTUBE_COOKIES=/app/cookies/youtube.txt`。
> 没放文件也不报错，纯可选。

## 3. 构建并启动

```bash
sudo docker-compose up -d --build
sudo docker-compose logs -f          # 看日志，Ctrl+C 退出
curl http://localhost:8765/health
```

`restart: unless-stopped` + healthcheck —— 开机自启、崩溃自重启。
启动后也能在 **CasaOS 界面**里看到 `video_transcript` 容器。

## 4. 让手机连树莓派

```bash
hostname -I        # Pi 局域网 IP，如 192.168.0.50
```

iOS 快捷指令的 `BASE` 改成 `http://192.168.0.50:8765`。
（CasaOS/Pi OS 默认无防火墙；若开了 ufw：`sudo ufw allow 8765/tcp`。）

## 5. 测一条

```bash
curl -X POST http://localhost:8765/jobs \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.bilibili.com/video/BV1e57j6UEyT","sync":true}'
```

返回带 `message` + `text`，且共享文件夹（W: / `OUTPUT_HOST_DIR`）下出现 `.md` 即成功。

## 常用运维

```bash
git pull                             # 拉最新代码（.env 不受影响，不在仓库里）
sudo docker-compose restart          # 只改了 .env 时重启
sudo docker-compose up -d --build    # 改了代码/依赖后重建
sudo docker-compose down             # 停
sudo docker-compose logs --tail=50   # 最近日志
```

## 关于权限

容器以 root 跑、写入 bind-mount 目录通常没问题。若发现 W: 里看不到/无权改文件，
检查共享文件夹属主，必要时 `sudo chown -R 1000:1000 /DATA/Documents/b站视频字幕`
（按你 CasaOS 的共享账号 uid/gid 调整）。

## 无字幕视频

平台无字幕（B站约25%、多为游戏/音乐/鬼畜；YouTube 视具体频道而异）时，
若已配置 `ASR_API_KEY`，会自动降级到云端 SenseVoiceSmall 转写，再生成摘要——
对 Pi 来说只是发个 HTTP 请求，不占算力。没配 `ASR_API_KEY` 且
`ENABLE_WHISPER=false` 时，会直接回执"无可用字幕"。
