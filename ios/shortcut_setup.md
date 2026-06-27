# iOS 快捷指令搭建指南

目标：在 B 站 App 里点「分享 → 你的快捷指令」，自动把链接发给本机服务，处理完弹通知。

> 每一步都标注了 **中文动作名（English action name）**，方便你在快捷指令 App 搜索框里直接搜英文名添加。

## 前置

- PC 上 `python server.py` 已启动。
- 手机能访问到 PC 地址，下文用 `BASE` 代表：
  - 同一 Wi-Fi：`http://192.168.0.152:8765`
  - 异地：装 Tailscale，换成 Tailscale IP，如 `http://100.x.x.x:8765`
- 若 `.env` 设了 `API_TOKEN`，所有 URL 后面加 `?token=你的token`。

---

## 方案 A：轮询版（推荐，长短视频都稳）

新建快捷指令（New Shortcut），按顺序加这些动作：

1. **接收分享输入**
   点快捷指令详情里的 ⓘ（或顶部设置）→ 打开 **在共享表单中显示（Show in Share Sheet）**，
   接收类型勾选 **URL** 和 **文本（Text）**。进来的内容就是变量 **快捷指令输入（Shortcut Input）**。

2. **文本（Text）**
   内容填入变量 `快捷指令输入（Shortcut Input）`。后面用它当作要提交的链接。
   > B 站 App 分享出来的是「简介 + b23.tv 短链」一整段文本。**直接整段发出去即可**，
   > 服务端会自动从中抠出 `b23.tv` 短链、跟随跳转拿到 BV 号——不用在快捷指令里自己提取链接。

3. **获取URL内容（Get Contents of URL）** —— 提交任务
   - URL：`BASE/jobs`
   - 方法（Method）：`POST`
   - 请求体（Request Body）：选 `JSON`
     - 加一个字段：键（Key）= `url`，值（Value）= 上一步的「文本（Text）」
   - 这个动作的输出就是返回的 JSON。

4. **获取词典值（Get Dictionary Value）**
   取 `获取 [值] 键为 [job_id] 的 [上一步词典]`（Get Value for `job_id` in Dictionary）。

5. **设置变量（Set Variable）**
   把上一步结果存为变量 `JOB`。

6. **重复（Repeat）** —— 选「重复 N 次」，N 填 `40`（约 40 次轮询）。循环体内放：
   1. **等待（Wait）** `4` 秒
   2. **获取URL内容（Get Contents of URL）**：方法 `GET`，URL = `BASE/jobs/` 后面接变量 `JOB`
      （把 `JOB` 变量直接拼在 URL 末尾即可。）
   3. **获取词典值（Get Dictionary Value）**：取键 `message`（Get Value for `message`）。
   4. **如果（If）**：条件设为 `message` **有任意值（has any value）**。
      - 内部：**显示通知（Show Notification）**，正文用上一步取到的 `message`（已是形如
        `✅ B站AI字幕 · 128条 · 标题` 的可读文案）。
      - 内部再加：**停止并退出快捷指令（Stop This Shortcut）**。
        （快捷指令没有「跳出循环」动作，用这个在拿到结果时直接结束。）

7. （可选）循环跑完仍没结果 → 加一个 **显示通知（Show Notification）**：内容「处理超时，请稍后查看」。

完成后命名快捷指令（如「B站字幕」）。在 B 站视频页点 **分享 → B站字幕** 即可触发。

---

## 方案 B：同步版（最简，仅适合短视频/有CC字幕的）

不想写循环，三步搞定：

1. **接收分享输入**（同上，Show in Share Sheet，接收 URL/文本）。
2. **获取URL内容（Get Contents of URL）**：
   - URL `BASE/jobs`，方法 `POST`，请求体 `JSON`
   - 字段：`url` = `快捷指令输入（Shortcut Input）`；再加 `sync` = `true`
3. **获取词典值（Get Dictionary Value）** 取键 `message` → **显示通知（Show Notification）** 显示它。

缺点：若降级到 Whisper 跑长视频，请求可能超时。长视频请用方案 A。

---

## 动作名中英对照速查

| 中文 | English |
|------|---------|
| 文本 | Text |
| 获取URL内容 | Get Contents of URL |
| 获取词典值 | Get Dictionary Value |
| 设置变量 | Set Variable |
| 重复 | Repeat |
| 等待 | Wait |
| 如果 | If |
| 停止并退出快捷指令 | Stop This Shortcut |
| 显示通知 | Show Notification |
| 在共享表单中显示 | Show in Share Sheet |
| 快捷指令输入 | Shortcut Input |

## 先用电脑验证服务可达

```bash
curl -X POST http://192.168.0.152:8765/jobs -H "Content-Type: application/json" \
  -d "{\"url\":\"https://www.bilibili.com/video/BVxxxx\",\"sync\":true}"
```
