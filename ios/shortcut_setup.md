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

## 摘要 + 整理（在上面任一方案后追加）

服务端响应里已带这些顶层字段（同步版直接有；轮询版在最终 `/jobs/<id>` 结果里）：

| 字段 | 内容 |
|------|------|
| `message` | 徽标 + 标题 + **摘要**（直接 Show Notification 就能扫一眼判断价值） |
| `summary` | 纯摘要文本 |
| `text` | 完整字幕（进剪贴板用） |
| `filename` | md 文件名，整理时要回传给服务端 |

### 设计：全文自动进剪贴板 + 摘要置顶菜单 + 动态文件夹归类

文件去向只有三类：**删除 / 保留 / 归类到文件夹**（"收藏"只是一个叫"收藏"的文件夹；
打标签 = 归类到对应文件夹）。复制全文是**正交**的——不管去留都有用，所以做成默认行为。

拿到结果后依次加：

1. **获取词典值** 取 `text` → **设置剪贴板（Set Clipboard）**　← 全文一回来就进剪贴板
2. **获取词典值** 取 `summary` → **设置变量** `SUM`
3. **获取词典值** 取 `filename` → **设置变量** `FN`
4. **从菜单中选取（Choose from Menu）**，**Prompt（提示）字段填变量 `SUM`**（摘要显示在菜单顶部），三项：
   - **删除**：`POST BASE/files/action`，JSON `filename`=`FN`、`action`=`delete`
   - **保留**：结束（全文已在剪贴板）
   - **归类**：进入下面的子流程

#### 「归类」子流程（选已有文件夹 / 新建）

1. **获取URL内容** `GET BASE/files/folders` → **获取词典值** 取 `folders`
2. **设置变量** `LIST` = 上一步的 folders；再 **添加到变量（Add to Variable）** `LIST` 一项文本 `➕ 新建文件夹`
3. **从列表中选取（Choose from List）** `LIST` → **设置变量** `PICK`
4. **如果（If）** `PICK` 是 `➕ 新建文件夹`：**要求输入（Ask for Input）** 文件夹名 → 重设 `PICK` 为输入
5. **获取URL内容** `POST BASE/files/action`，JSON：`filename`=`FN`、`action`=`tag`、`tag`=`PICK`
6. **显示通知** 返回的 `message`（📁 已移动到「xxx」）

> `tag` 动作 = 移进 `<tag>/` 文件夹，不存在自动新建。第一次输个新名，以后就出现在 `folders` 列表里。
> 安全：服务端只允许操作输出目录内的文件，自动拦截路径穿越。

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
| 从菜单中选取 | Choose from Menu |
| 从列表中选取 | Choose from List |
| 添加到变量 | Add to Variable |
| 要求输入 | Ask for Input |
| 设置剪贴板 | Set Clipboard |

## 先用电脑验证服务可达

```bash
curl -X POST http://192.168.0.152:8765/jobs -H "Content-Type: application/json" \
  -d "{\"url\":\"https://www.bilibili.com/video/BVxxxx\",\"sync\":true}"
```
