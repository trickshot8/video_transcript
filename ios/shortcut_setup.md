# iOS 快捷指令搭建指南

目标：B 站 / YouTube App 里点「分享 → 你的快捷指令」→ 自动发给树莓派服务 → 处理完弹出
「摘要 + 决策菜单」，一步决定这条字幕的去留（删除/保留/归类），全文自动进剪贴板。

> 服务端按链接自动识别 B站还是 YouTube，**快捷指令完全不用区分平台**——同一套流程，
> 分享的链接原样发出去就行。

> 每步都标了 **中文动作名（English action name）**，可直接在快捷指令 App 搜索框搜英文名添加。

## 前置

- 树莓派上服务已跑起来（`sudo docker-compose up -d`）。
- 手机能访问到树莓派，下文用 `BASE` 代表 `http://<PiIP>:8765`：
  - `<PiIP>` = 树莓派局域网 IP（Pi 上 `hostname -I` 查，如 `192.168.0.169`）
  - 同一 Wi-Fi 直接用内网 IP；异地用 Tailscale IP
- 若 `.env` 设了 `API_TOKEN`，所有 URL 加 `?token=你的token`（默认没设，不用管）。

> 所有接口路径都要带 `BASE` 前缀：`BASE/jobs`、`BASE/jobs/<id>`、`BASE/files/folders`、`BASE/files/action`。

---

## 为什么用异步（轮询）

服务端处理完才有结果。**异步**是：先拿一张"取件号"`job_id`，再轮询直到完成。
好处是无论快慢都不会超时——B站字幕几秒就好（第一次轮询即返回，几乎瞬间），
未来若用 Whisper 跑长视频（几分钟）也扛得住。关键技巧：**拿到结果就存进 `RESULT`
变量、后续循环空转跳过**，这样菜单逻辑能放在循环外面，不用层层嵌套。

---

## 完整搭建步骤

### 设置：接收分享
快捷指令详情 ⓘ → 打开 **在共享表单中显示（Show in Share Sheet）**，接收类型勾 **URL + 文本**。
进来的内容是变量 **快捷指令输入（Shortcut Input）**。

> B 站分享出来是「简介 + b23.tv 短链」一整段文本，**整段直接发**即可，服务端自动抠短链、跟跳转拿 BV 号。

### 提交任务
1. **获取URL内容（Get Contents of URL）**
   - URL：`BASE/jobs`
   - 方法：`POST`
   - 请求体：`JSON`，字段 `url`（文本）= **快捷指令输入**
   - （**不要**加 `sync`，走异步）
2. **获取词典值（Get Dictionary Value）** 取 `job_id` → **设置变量（Set Variable）** `JOB`

### 轮询直到完成
3. **重复（Repeat）** `60` 次，循环体：
   - **如果（If）** 变量 `RESULT` **没有任何值（does not have any value）**：　← 拿到结果后就不再轮询
     1. **等待（Wait）** `3` 秒
     2. **获取URL内容**：方法 `GET`，URL = `BASE/jobs/` 末尾拼接变量 `JOB`
     3. **获取词典值** 取 `message`（**完成或失败时才有 `message`，处理中没有**）
     4. **如果** `message` **有任意值（has any value）**：　← 一个条件同时覆盖"完成"和"失败"
        - **设置变量** `RESULT` = 上面 GET 的结果（整个应答词典）

### 处理结果（循环之后，不嵌套）
4. **如果** `RESULT` **没有任何值**（超时）→ **显示通知** 「处理超时，稍后看共享盘」→ 结束。
   **否则** 继续：
5. **获取词典值** 从 `RESULT` 取 `text` → **设置剪贴板（Set Clipboard）**　← 全文进剪贴板
6. **获取词典值** 取 `summary` → **设置变量** `SUM`
7. **获取词典值** 取 `filename` → **设置变量** `FN`
8. **从菜单中选取（Choose from Menu）**，**Prompt（提示）= 变量 `SUM`**（摘要显示在菜单顶部），三项：

| 菜单项 | 这一支放什么 |
|--------|-------------|
| **删除** | **获取URL内容** `POST BASE/files/action`，JSON `filename`=`FN`、`action`=`delete` → 取 `message` → **显示通知** |
| **保留** | **显示通知**「✅ 已保留并复制全文」（全文已在剪贴板，结束） |
| **归类** | 见下方子流程 |

### 「归类」子流程（放进菜单的"归类"那一支）

> 思路：列出已有文件夹 + 一项"➕ 新建"。选已有就用它，选新建就输名字。
> 两种情况最后**走同一个保存动作**（合流），服务端发现文件夹不存在会自动新建。

1. **获取URL内容** `GET BASE/files/folders` → **获取词典值** 取 `folders`（这是个列表）
2. **设置变量** `LIST` = 上一步 `folders`
3. **文本（Text）** 内容 `➕ 新建文件夹` → **添加到变量（Add to Variable）** 加到 `LIST`
   （顺序不能反：先 Set 装上列表，再 Add 追加一项 → `LIST = [已有文件夹…, "➕ 新建文件夹"]`）
4. **从列表中选取（Choose from List）** `LIST` → **设置变量** `PICK`
5. **如果（If）** `PICK` **是** `➕ 新建文件夹`：
   - **要求输入（Ask for Input）** 文件夹名 → **设置变量** `PICK` = 输入结果
   - （结束如果）
6. **获取URL内容** `POST BASE/files/action`，JSON：`filename`=`FN`、`action`=`tag`、`tag`=`PICK`
7. **获取词典值** 取 `message` → **显示通知**（📁 已移动到「xxx」）

---

## 变量速查

| 变量 | 来自 | 用途 |
|------|------|------|
| `JOB` | `job_id` | 轮询用的取件号 |
| `RESULT` | 完成时的应答 | 存最终结果，循环外统一处理 |
| `SUM` | `summary` | 菜单顶部摘要 |
| `FN` | `filename` | 整理时回传给服务端 |
| `PICK` | 列表选择/输入 | 目标文件夹名 |
| （剪贴板）| `text` | 全文，随手粘去分析 |

## 服务端响应字段（顶层）

| 字段 | 内容 |
|------|------|
| `status` | `queued`/`processing`/`done`/`error` |
| `message` | 徽标 + 标题 + 摘要（完成/失败才有） |
| `summary` | 纯摘要文本 |
| `text` | 完整字幕（带标点） |
| `filename` | md 文件名 |

## 动作名中英对照

| 中文 | English |
|------|---------|
| 文本 | Text |
| 获取URL内容 | Get Contents of URL |
| 获取词典值 | Get Dictionary Value |
| 设置变量 | Set Variable |
| 重复 | Repeat |
| 等待 | Wait |
| 如果 | If |
| 显示通知 | Show Notification |
| 在共享表单中显示 | Show in Share Sheet |
| 快捷指令输入 | Shortcut Input |
| 从菜单中选取 | Choose from Menu |
| 从列表中选取 | Choose from List |
| 添加到变量 | Add to Variable |
| 要求输入 | Ask for Input |
| 设置剪贴板 | Set Clipboard |

## 先用命令行验证服务可达

```bash
curl -s -X POST http://<PiIP>:8765/jobs -H "Content-Type: application/json" \
  -d '{"url":"https://www.bilibili.com/video/BVxxxx","sync":true}'
curl -s http://<PiIP>:8765/files/folders
```
（`sync:true` 仅用于命令行快速验证；手机端用上面的异步轮询。）
