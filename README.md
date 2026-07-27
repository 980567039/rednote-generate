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

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Pinia、Vue Router
- 后端：Python 3.11+、Flask、Pillow、PyYAML
- 模型接口：文本和图片服务商均通过本地设置配置，可使用 OpenAI-compatible 接口
- 数据：历史记录和生成图片默认保存在本地 `history/` 目录

## 快速开始

### macOS 一键启动

需要 Python 3、Node.js，以及 `pnpm` 或 `npm`。

```bash
./scripts/start-macos.command
```

启动脚本会检查依赖和端口，启动前端与后端，并在退出时清理本次启动的子进程。

- 前端：http://localhost:5173
- 后端健康检查：http://localhost:12398/api/health

按 `Ctrl+C` 或关闭启动窗口即可停止服务。也可以使用对应的 `scripts/start-linux.sh` 或 `scripts/start-windows.bat`。

### 手动启动

```bash
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
- 旅游攻略中的实时信息必须以景点、交通和票务官方渠道为准。
- 本项目仅负责本地创作流程，不承诺第三方模型服务商的可用性、计费或内容安全策略。

## License

本项目遵循仓库中的 [LICENSE](LICENSE) 文件。
