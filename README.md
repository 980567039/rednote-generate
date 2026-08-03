# AI 图文创作工作台

一个面向小红书图文创作的本地 AI 工作台：输入主题、目的地或补充要求，生成可编辑的大纲、配图、标题、正文和标签，并保留完整历史记录。

![首页示例](history/task_e6f0acff/thumb_0.png)

## 能做什么

- 自由创作：教程、观点、前后对比、清单和故事类图文。
- 旅游攻略：输入目的地，选择游玩时长、同行人群和旅行偏好，生成路线型攻略。
- 结构预设：标准 5 页、前后对比 2 页、完整对比 4 页；旅游攻略会按半天、一天或两天自动选择页数。
- 大纲编辑：修改页面内容、拖拽排序、添加或删除页面，自动保存到历史记录。
- 图片生成：支持预览大图、重新生成，以及在重新生成时填写本次修改意见。
- 文案生成：生成多个标题、正文和标签；成品内容与历史作品绑定保存。
- 任务状态：展示排队、生成中、完成、失败和待确认状态，支持失败图片重试。
- 今日灵感：内置本地演示主题，不依赖外部热榜抓取。
- 外观设置：跟随系统、浅色和暗色主题。
- 服务商设置：在系统设置中配置文本/图片模型、Base URL、端点和 API Key。
- 小红书发布：在成品页检查标题、正文、标签和图片后，通过本机 Chrome 预填或自动提交。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Pinia、Vue Router
- 后端：Python 3.11+、Flask、Pillow、PyYAML、WebSockets
- 模型接口：文本和图片服务商均通过本地设置配置，可使用 OpenAI-compatible 接口
- 数据：历史记录和生成图片默认保存在本地 `history/` 目录

## 快速开始

### macOS 一键启动

需要 Python 3、Node.js，以及 `pnpm` 或 `npm`。

```bash
./scripts/start-macos.command
```

启动脚本会检查依赖和端口，启动前端与后端，并在退出时清理本次启动的子进程。
如果发布组件尚未初始化，脚本会先初始化固定版本的 Git 子模块；初始化失败不会影响生成和下载功能。

- 前端：http://localhost:5173
- 后端健康检查：http://localhost:12398/api/health

按 `Ctrl+C` 或关闭启动窗口即可停止服务。也可以使用对应的 `scripts/start-linux.sh` 或 `scripts/start-windows.bat`。

### 手动启动

```bash
# 首次克隆或首次使用发布功能
git submodule update --init third_party/XiaohongshuSkills

# 后端
uv sync
uv run flask --app backend.app:create_app run --host 127.0.0.1 --port 12398

# 前端（另开一个终端）
cd frontend
pnpm install
pnpm dev --host 127.0.0.1
```

### Docker

```bash
docker compose up --build
```

Docker 模式访问 http://localhost:12398。首次使用仍需在系统设置中填写模型服务商配置。

Docker 容器无法直接控制宿主机已登录的 Chrome，因此小红书发布功能默认只支持本机启动模式。

停止 Docker 服务：

```bash
docker compose down
```

## 模型配置

启动后打开「系统设置」，分别添加文本和图片服务商：

1. 选择服务商类型（例如 `openai_compatible`）。
2. 填写 Base URL、模型名称、对应端点和 API Key。
3. 保存后使用“测试连接”确认配置。

本项目不内置任何 API Key，也不会把密钥写入 README、Git 历史或前端构建产物。`text_providers.yaml` 和 `image_providers.yaml` 位于本地并被 `.gitignore` 忽略。

## 发布到小红书

发布功能基于 [XiaohongshuSkills](https://github.com/white0dew/XiaohongshuSkills) 控制一个独立的本机 Chrome Profile，不是小红书官方 API。首次使用建议：

1. 在「系统设置 → 小红书发布」确认组件可用，保留默认的“预填后确认”。
2. 点击“打开登录窗口”，在独立 Chrome 中扫码登录测试账号。
3. 进入一条已完成的成品，在最终页点击“发布到小红书”。
4. 选择标题并检查正文、标签和图片，然后创建预填任务。
5. 浏览器填写完成后人工检查，再回到弹窗确认发布。

也可以主动选择“自动发布”，此模式会在上传和填写完成后直接点击发布按钮。页面只有拿到明确的笔记链接时才显示“发布成功”；如果只确认按钮已点击，会显示“已提交、待核实”，避免把不确定结果误报为成功。

发布配置和任务状态分别保存在本地 `publish_config.yaml`、`publish_tasks.json`，两者均被 Git 忽略。账号登录态保存在第三方组件的独立 Chrome Profile 中，应用不保存账号密码，也不会把 Cookie 返回给前端。

自动化网页操作可能随小红书页面改版失效，也存在限流或账号风控风险。请先使用测试账号、控制频率并人工复核内容；状态不确定时不要自动重试，以免重复发布。

### 登录状态排查

- 「账号配置名」是本机 Chrome Profile 的标识，不是小红书昵称。单账号使用时留空，组件会使用默认 Profile；只有已经在发布组件中创建过的账号名才应填写在这里。
- 点击「打开登录页」后，必须在新打开的发布专用 Chrome 窗口中扫码。普通 Chrome 窗口里的登录态不会被发布器使用；扫码后等待页面进入创作者中心，再回到系统设置点击「检查登录」。
- 发布器默认使用本机 `127.0.0.1:9222` 调试端口。这个端口不是模型 API 代理端口，也不需要填写小红书网址或 API Key。
- 如果提示未登录但你刚完成扫码，先确认发布专用 Chrome 窗口仍在运行，再重新点击「检查登录」。不要在不同账号配置之间来回切换，以免连接到另一个 Profile。
- 如果提示浏览器启动或连接失败，而不是明确的“未登录”，检查端口是否监听：

  ```bash
  lsof -nP -iTCP:9222 -sTCP:LISTEN
  uv run python third_party/XiaohongshuSkills/scripts/cdp_publish.py \
    --host 127.0.0.1 --port 9222 check-login
  ```

  `NOT_LOGGED_IN` 表示确实需要重新扫码；`Failed to start Chrome` 或端口未监听则表示发布专用 Chrome 没有启动成功，需要先退出残留的发布窗口、重新启动项目后再检查。登录态保存在 `~/Google/Chrome/XiaohongshuProfiles/`，不要删除该目录，否则需要重新扫码。

## 旅游攻略模式

首页切换到「旅游攻略」后，输入例如：

> 北京故宫

然后选择时长、同行人群和偏好。系统会生成路线顺序、时间安排、拍照点、休息建议和避坑提示，并将不确定的开放时间、票务、预约及交通信息标记为需要以官方信息核验。

当前旅游攻略是本地模型体验版，没有接入实时地图、票务或景区公告接口。发布前请人工核对官方信息。

## 常见问题

### 图片生成约 60 秒后断开

这通常是 API 网关或反向代理的上游读取超时。项目客户端允许等待约 300 秒，网关的 upstream/proxy read timeout 也建议设置为至少 300 秒；仅设置 keepalive 不能替代读取超时。

### 连接测试返回 401、404 或 429

- `401`：检查 API Key 是否有效。
- `404`：检查模型名、Base URL 和 endpoint 是否匹配。
- `429`：通常是配额或限流，等待后重试或调整服务商额度。

Base URL 与 endpoint 应分别填写，不要把完整请求地址重复填入两个字段。

### 端口已被占用

先回到原启动终端按 `Ctrl+C` 正常停止。也可检查占用进程：

```bash
lsof -nP -iTCP:12398 -sTCP:LISTEN
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

## 目录结构

```text
backend/                 Flask API、模型适配器、提示词和历史服务
frontend/src/            Vue 页面、组件、状态管理和主题
frontend/public/         首页展示素材
history/                 本地历史记录与生成图片
scripts/                 macOS/Linux/Windows 启动脚本
tests/                   后端回归测试
third_party/             固定版本的小红书浏览器发布组件
```

## 验证项目

```bash
python3 -m compileall -q backend tests
.venv/bin/pytest -q

cd frontend
./node_modules/.bin/vue-tsc --noEmit
./node_modules/.bin/vite build
```

## 示例历史记录

仓库包含 4 条用于本地验收的历史记录和对应图片，覆盖旅游攻略、AI 视觉创作和教程类内容。它们不包含 API Key 或本机配置，可直接在本地启动后查看。

![旅游攻略示例](history/task_e6f0acff/thumb_0.png)
![视觉创作示例](history/task_a7e81f22/thumb_0.png)

## 重要说明

- 图片和历史内容可能较大，默认适合本地验证，不建议把真实用户数据直接提交到公开仓库。
- 小红书发布仅面向本机个人工作流；Vercel 等无本地 Chrome/Profile 的环境不能直接使用。
- 旅游攻略中的实时信息必须以景点、交通和票务官方渠道为准。
- 本项目仅负责本地创作流程，不承诺第三方模型服务商的可用性、计费或内容安全策略。

## License

本项目遵循仓库中的 [LICENSE](LICENSE) 文件。`third_party/XiaohongshuSkills` 是独立的 MIT 许可组件，其版权与许可声明保留在子模块内。
