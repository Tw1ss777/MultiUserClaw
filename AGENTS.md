# MultiUserClaw — 开发指南

面向 AI 编程助手和平台二次开发者的项目全景文档。

## 项目概览

MultiUserClaw 是一个轻量级 **AI SaaS 多租户平台**，基于 Hermes Agent 改造。核心能力：

- **多租户隔离**：每个用户拥有独立的 Docker 容器运行 AI Agent
- **多渠道接入**：微信、Telegram、Discord、飞书、Slack 等 20+ 渠道
- **LLM 代理**：统一代理层，支持 Anthropic/OpenAI/DeepSeek/通义千问/Kimi 等
- **Web 管理后台**：Agent 管理、会话历史、定时任务、文件管理、技能市场

## 总体架构

```
浏览器 ──→ frontend (Vite React, :3080)
               │
               ▼
          platform/gateway (FastAPI, :8080)
               │
          ┌────┴────┐
          ▼         ▼
     PostgreSQL    Docker Engine
     (:15432)      │
                   ├── hermes-user-<id>  ← 每用户独立容器（Dedicated 模式）
                   └── shared-openclaw   ← 共享运行时（Shared 模式）
```

**数据流**：
1. 用户通过 Frontend 登录，获取 JWT Token
2. 所有 `/api/openclaw/*` 请求由 Gateway 鉴权后转发到对应用户的容器
3. 容器内的 Hermes Agent 通过 Gateway 的 LLM 代理访问大模型（用户不直接持有 API Key）
4. 消息渠道由 Hermes Agent 的 Gateway 模块直接处理(WebSocket/Webhook)

## 目录地图

```
MultiUserClaw/
├── platform/            ← ★ 核心后端：FastAPI 网关 + 容器管理 + LLM 代理
│   ├── app/
│   │   ├── main.py          # FastAPI 应用入口，lifespan 事件
│   │   ├── config.py        # pydantic-settings 配置（PLATFORM_* 环境变量）
│   │   ├── routes/
│   │   │   ├── proxy.py         # ★ 核心反向代理 → 用户容器
│   │   │   ├── auth.py          # 注册/登录/JWT/SSO
│   │   │   ├── admin.py         # 管理员接口（用户管理、用量统计）
│   │   │   ├── llm.py           # LLM 代理（litellm 多供应商路由）
│   │   │   └── models.py        # 模型列表配置
│   │   ├── api_compat/          # OpenClaw 兼容 API（skills/marketplace）
│   │   ├── container/           # Docker 容器生命周期管理
│   │   ├── runtime_backends/    # Hermes/OpenClaw runtime 适配层
│   │   ├── auth/                # JWT 生成/验证、用户 CRUD
│   │   ├── db/                  # SQLAlchemy async engine + models
│   │   └── model_config.py      # 模型配置持久化（按用户/全局）
│   ├── alembic/             # 数据库迁移
│   ├── tests/               # pytest 测试
│   └── pyproject.toml       # Python 依赖（FastAPI, SQLAlchemy, docker-py 等）
│
├── frontend/            ← ★ 主用户前端（Vite + React 19 + Tailwind 4）
│   ├── src/
│   │   ├── App.tsx           # 路由表
│   │   ├── lib/api.ts        # ★ 所有 API 调用封装（fetchJSON + JWT 刷新）
│   │   ├── components/       # 通用组件（Sidebar, Layout, Brand, Chat 等）
│   │   └── pages/            # 页面组件（一一对应路由）
│   └── package.json          # React 19, react-router-dom 7, lucide-react
│
├── manage_front/        ← 管理后台（Next.js 15）
│   └── src/                 # 用户管理、系统配置
│
├── simple_front/        ← 简化版前端（Vite React）
│
├── hermes-agent/        ← Hermes Agent 子模块（已有自己的 AGENTS.md）
│   ├── agent/           # Agent 核心循环
│   ├── gateway/         # 消息平台网关（Telegram/Discord/Slack 等适配器）
│   ├── tools/           # 工具实现（terminal/file/web/browser/mcp/...）
│   ├── plugins/         # 内置插件（memory 系统、model-providers 等）
│   ├── cron/            # 定时任务调度
│   └── Dockerfile.bridge # Hermes runtime 镜像构建
│
├── deploy_copy/         ← 部署配置模板（复制到各镜像中）
│   ├── openclaw_defaults.json  # ★ Agent 默认配置（6 个预设 Agent、tools、memory）
│   ├── Agents/              # 预设 Agent 目录（main/manager/programmer/researcher/hr/doctor）
│   └── skills/              # 预装技能
│
├── docker-compose.yml   ← ★ Docker 部署编排
├── deploy_docker.py     ← 一键部署脚本（构建+启动+健康检查）
├── start_local.py       ← 本地开发启动脚本（macOS/Linux/Windows）
├── build_once.py        ← 离线/国内网络构建脚本（镜像源加速）
├── prepare.py           ← 离线部署材料准备
├── .env.example         ← ★ 环境变量参考（LLM Key、容器配置、SSO）
└── pyproject.toml       ← 根级 Python 项目配置
```

## 服务拓扑

### Docker 部署模式

| 服务 | 镜像 | 端口 | 网络 |
|------|------|------|------|
| `postgres` | `postgres:16-alpine` | `15432:5432` | `openclaw-internal` |
| `gateway` | `openclaw_gateway:latest` | `8080:8080` | `internal` + `external` |
| `frontend` | `openclaw_frontend:latest` | `3080:3000` | `openclaw-external` |
| `manage-front` | `openclaw_manage-front:latest` | `3081:3000` | `openclaw-external` |
| `simple-front` | `openclaw_simple-front:latest` | `3082:3000` | `openclaw-external` |
| `hermes-user-*` | `nanobot-hermes-agent:latest` | 动态分配 | `openclaw-internal` |

- **两个网络**：`openclaw-internal`（gateway↔DB↔用户容器），`openclaw-external`（前端→gateway）
- Gateway 挂载 `/var/run/docker.sock` 以动态创建/管理用户容器

### 本地开发模式（`start_local.py`）

| 服务 | 端口 | 说明 |
|------|------|------|
| PostgreSQL (Docker) | `5432` | 自动创建 openclaw-postgres-dev 容器 |
| OpenClaw Bridge | `18080` | Hermes Agent 开发模式（tsx 热重载） |
| Platform Gateway | `8080` | FastAPI + uvicorn --reload |
| Frontend Dev Server | `3080` | Vite HMR |

## 关键设计决策

### 1. 为什么用 Hermes 替代原生 OpenClaw

- Hermes 是 OpenClaw 的下游 fork，保持 API 路径 `/api/openclaw/*` 兼容
- Hermes 的 Profile 机制天然支持多实例（每用户一个 HERMES_HOME）
- Hermes 的工具链更丰富（terminal、browser、code execution、MCP 等）
- 平台通过 `PLATFORM_DEDICATED_RUNTIME_BACKEND=hermes` 切换，可回滚到 `openclaw`

### 2. Dedicated vs Shared 模式

| 维度 | Dedicated | Shared |
|------|-----------|--------|
| 隔离级别 | Docker 容器级隔离（2GB RAM, 4 CPU） | 逻辑隔离 |
| 适用场景 | 高安全要求、重度使用 | 轻量用户、降低成本 |
| LLM 用量追踪 | 按用户精确计费 | 共享 token，粗粒度统计 |
| 配置方式 | `runtime_mode=dedicated`（默认） | `runtime_mode=shared` |

### 3. API Key 安全模型

- LLM API Key 仅存于 Gateway 环境变量中
- 用户容器**不直接持有**任何 LLM API Key
- 容器通过 `/api/openclaw/models/config` 获得模型列表，LLM 调用通过 Gateway 代理
- Gateway 使用 `litellm` 做多供应商智能路由（按模型名前缀/关键词匹配 provider）

### 4. 兼容 API 层

所有 `/api/openclaw/*` 路径保持 OpenClaw 兼容：
- 前端的 API 调用无需改动
- Gateway 内部将请求转换为 Hermes API 调用
- 不支持的能力（如 plugin 安装）返回明确错误

## 开发工作流

### 本地开发

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填写一个 LLM API Key

# 2. 安装 Python 依赖
cd platform && pip install -e ".[dev]" && cd ..

# 3. 拉取 Hermes 依赖（首次）
cd hermes-agent && npm install && cd ..

# 4. 一键启动
python start_local.py

# 启动单个服务
python start_local.py --only gateway,frontend

# 跳过某服务
python start_local.py --skip bridge

# 停止所有
python start_local.py --stop
```

### Docker 部署

```bash
# 完全重新构建 + 启动
python deploy_docker.py

# 仅重建 Hermes 基础镜像（如改了 Dockerfile.bridge）
python deploy_docker.py --rebuild hermes

# 使用缓存快速重建
python deploy_docker.py --rebuild hermes --fast

# 重建前端
python deploy_docker.py --rebuild frontend

# 重建多个服务
python deploy_docker.py --rebuild gateway,frontend

# 指定服务器 IP
python deploy_docker.py --host 192.168.1.160

# 反向代理部署
python deploy_docker.py --host 117.133.60.219 --relative-api

# 清理全部数据
python deploy_docker.py --clean
```

### Hermes Agent 子模块开发

详见 `hermes-agent/AGENTS.md`，涵盖：
- Agent 核心循环 (AIAgent 类)
- 工具注册机制 (registry.py)
- Slash Command 系统
- Profile 多实例支持
- 测试体系（~3000 tests）

关键约束：修改 hermes-agent 后需重新构建镜像：
```bash
python deploy_docker.py --rebuild hermes
# 或本地开发模式自动热重载
```

## 常见操作指南

### 添加新的消息渠道

以微信为例 (`@tencent-weixin/openclaw-weixin-cli`)：

1. **在 Hermes 镜像中预装插件**：修改 `hermes-agent/Dockerfile.bridge`，添加：
   ```dockerfile
   RUN npm install -g @tencent-weixin/openclaw-weixin-cli
   ```
2. **重新构建镜像**：`python deploy_docker.py --rebuild hermes --fast`
3. **在前端渠道管理页配置**：渠道管理 → 点击"微信" → 扫码绑定
4. **渠道已在 `Channels.tsx` 注册**，新渠道需添加配置字段到 `CHANNEL_CONFIG_FIELDS`

注意：Hermes runtime 不支持通过前端"插件管理"页面安装 npm 插件（被 Gateway 代理拦截）。

### 添加新的 LLM Provider

1. 在 `.env.example` 中添加 `XXX_API_KEY=` 示例
2. Gateway 的 `app/routes/llm.py` 路由层通过 litellm 自动识别 provider 前缀
3. 模型命名规则：`provider/model-name`（如 `dashscope/qwen-turbo`）

### 修改 Agent 默认配置

编辑 `deploy_copy/openclaw_defaults.json`：
- `agents.defaults` — 全局默认（超时、子代理限制）
- `agents.list` — 预设 Agent（main/manager/programmer/researcher/hr/doctor）的工具权限
- `tools.elevated` — 高危工具的白名单
- `memory` — 记忆系统配置（后端、搜索策略）

修改后需 `python deploy_docker.py --rebuild hermes` 生效。

### 前端开发

```bash
cd frontend
npm install
npm run dev        # 开发模式 (Vite HMR, :5173)
npm run build      # 生产构建
```

- 路由定义在 `App.tsx`
- API 调用封装在 `lib/api.ts`（含 JWT 自动刷新）
- 侧边栏菜单在 `components/Sidebar.tsx`
- 渠道绑定逻辑在 `pages/Channels.tsx`
- 插件安装/卸载在 `pages/Plugins.tsx`

### 数据库管理

```bash
# 查看迁移状态
cd platform && alembic current

# 生成新迁移
alembic revision --autogenerate -m "描述"

# 执行迁移
alembic upgrade head
```

## 配置速查

### 核心环境变量（`PLATFORM_` 前缀）

| 变量 | 说明 |
|------|------|
| `PLATFORM_DATABASE_URL` | PostgreSQL 连接串 |
| `PLATFORM_JWT_SECRET` | JWT 签名密钥 |
| `PLATFORM_DEFAULT_MODEL` | 新用户默认模型 |
| `PLATFORM_DEDICATED_RUNTIME_BACKEND` | `hermes` 或 `openclaw` |
| `PLATFORM_HERMES_IMAGE` | Hermes 容器镜像名 |
| `PLATFORM_OPENCLAW_IMAGE` | OpenClaw 回退镜像名 |
| `PLATFORM_CONTAINER_MEMORY_LIMIT` | 用户容器内存限制（默认 2g） |
| `PLATFORM_SHARED_HERMES_URL` | Shared Hermes runtime 地址 |
| `PLATFORM_ADMIN_USERNAME/PASSWORD` | 自动创建的管理员账号 |

### LLM API Key 变量

`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `KIMI_API_KEY`, `ZHIPU_API_KEY`, `DOUBAO_API_KEY`, `AIHUBMIX_API_KEY`, `EVOLINK_API_KEY`, `OPENROUTER_API_KEY`, `HOSTED_VLLM_API_KEY`, `MINIMAX_API_KEY`

## 项目边界

- **Hermes Agent 内核修改** → 在 `hermes-agent/` 子目录，遵循 `hermes-agent/AGENTS.md`
- **平台层（Gateway/容器管理/LLM代理/前后端）** → 在本仓库根目录修改
- **多用户隔离** → 由平台层保证，不对 Hermes Agent 内核侵入
- **兼容性承诺** → `/api/openclaw/*` 路径保持向后兼容
