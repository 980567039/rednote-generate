# AI 图文创作工具

本地运行的 AI 图文创作应用，支持文本大纲与配图生成。

## 本地启动

macOS 可双击 `scripts/start-macos.command`，或在项目目录运行：

```bash
./scripts/start-macos.command
```

启动后访问 http://localhost:5173，在「系统设置」中配置文本和图片模型。

## Docker

```bash
docker compose up --build
```

访问 http://localhost:12398。

## 开发与验证

```bash
uv sync
cd frontend && pnpm install
```

```bash
.venv/bin/pytest -q
cd frontend && ./node_modules/.bin/vue-tsc --noEmit && ./node_modules/.bin/vite build
```
