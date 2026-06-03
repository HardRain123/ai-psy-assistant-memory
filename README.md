# 心理咨询 Agent 后端 MVP

这是一个供 Dify HTTP Request 节点调用的心理支持/情绪陪伴/自助反思后端服务。当前 MVP 支持 50 分钟咨询 session 管理、长期记忆保存、咨询总结保存、上下文聚合、自动结束 session、后台任务扫描、咨询交接文档生成，以及 SQLite 本地开发和 PostgreSQL 线上部署。

重要边界：本系统不是医疗诊断工具，不能替代专业心理咨询、精神科医生或紧急救援。上线公开使用前必须增加鉴权、访问控制、隐私授权和数据删除流程。

## 功能清单

- `GET /health`：服务和数据库健康检查。
- `GET /session/status/{user_id}`：创建/查询咨询 session，保留 Dify 兼容字段。
- `POST /session/start/{user_id}`：显式开始新咨询，遵守每天一次限制。
- `POST /session/finalize`：幂等结束 session，并触发总结/记忆/交接文档流程。
- `GET /memory/{user_id}`、`POST /memory`：长期记忆读取和保存，支持 session 维度去重。
- `POST /session-message`、`GET /session-transcript/{session_id}`：保存和读取咨询消息。
- `POST /session-summary`：保存咨询总结。
- `GET /context/{user_id}`：聚合长期画像、最近总结和记忆，供 Dify 注入上下文。
- `POST /profile`、`GET /profile/{user_id}`：长期画像。
- `POST /care-plan`、`GET /care-plan/{user_id}`：咨询计划表。
- `POST /handoff/generate/{session_id}`：生成咨询交接文档。
- `GET /handoff/{document_id}`：查询交接文档。
- `GET /handoff/session/{session_id}`：查询某个 session 的交接文档。
- `GET /handoff/user/{user_id}`：查询某个用户的交接文档列表。
- `GET /handoff/export/{document_id}`：导出 Markdown/JSON 内容。
- `GET /handoff/export/user/{user_id}`：按用户导出用户级交接文档，整合长期画像、计划表、最近多次 session、长期记忆和风险记录。

## 本地启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

根目录 `main.py` 仍保留 `from app.main import app`，兼容旧的 `uvicorn main:app` 启动方式。`Procfile` 已指向 `app.main:app`。

## 环境变量

参考 `.env.example`：

- `DATABASE_URL`：数据库连接。默认 `sqlite:///data.db`。
- `APP_ENV`：运行环境，例如 `development` 或 `production`。
- `SESSION_LIMIT_MINUTES`：单次咨询时长，默认 `50`。
- `LOG_LEVEL`：日志等级，默认 `INFO`。
- `TASK_WORKER_ENABLED`：是否启动后台扫描线程，默认 `true`。
- `TASK_SCAN_INTERVAL_SECONDS`：后台扫描间隔，默认 `60`。
- `ENABLE_DEBUG_ENDPOINTS`：是否启用调试接口，默认 `false`。

本项目不在代码里写死数据库账号、密码或 API Key。

## SQLite 本地开发

默认配置：

```text
DATABASE_URL=sqlite:///data.db
```

应用启动时会执行 `init_db()`，自动创建或补齐表结构。SQLite 适合本地开发和小范围调试，不建议作为线上多实例服务数据库。

## PostgreSQL 线上配置

线上设置：

```text
DATABASE_URL=postgresql://user:password@host:5432/dbname
APP_ENV=production
SESSION_LIMIT_MINUTES=50
LOG_LEVEL=INFO
```

依赖中已包含 `psycopg[binary]`。应用启动时同样会执行 `init_db()` 创建表和索引。也可以参考 [docs/postgresql_schema.sql](docs/postgresql_schema.sql) 先手动建表。

## 数据表

MVP 使用这些核心表：

- `users`
- `sessions`
- `memories`
- `session_summaries`
- `session_messages`
- `user_profiles`
- `care_plans`
- `session_task`
- `session_task_history`
- `handoff_documents`

`session_task` 用于当前待处理任务，`session_task_history` 用于记录每次执行历史。当前任务类型以 `auto_end_session` 为主，预留 `generate_session_summary`、`save_memory`、`generate_handoff_document` 的扩展空间。

## session/status 返回示例

```json
{
  "session_id": "6e1f...",
  "status": "open",
  "started_at": "2026-06-02T12:00:00",
  "ended_at": null,
  "elapsed_minutes": 0.02,
  "remaining_minutes": 49.98,
  "stage": "trust",
  "session_stage": "trust",
  "is_new_session": true,
  "is_new_session_str": "true",
  "can_continue": true,
  "can_start_new_session": false,
  "daily_limit_reached": false,
  "message": "可以开始今天的新咨询。",
  "final_saved": false,
  "risk_level": "none"
}
```

保留字段：`session_id`、`status`、`started_at`、`ended_at`、`elapsed_minutes`、`remaining_minutes`、`stage`、`session_stage`、`is_new_session`、`is_new_session_str`、`can_continue`、`can_start_new_session`、`daily_limit_reached`、`message`。

Dify 友好的 `session_stage` 当前包括：`trust`、`deep`、`reframe`、`action`、`ending`、`ended`。新会话创建时 `is_new_session=true`；当天咨询结束后 `daily_limit_reached=true`。

## 自动结束逻辑

- 用户访问 `/session/status/{user_id}` 时，如果最近 open session 已超过 50 分钟，会自动结束。
- 如果存在昨天或更早的 open session，访问状态接口时会先结束旧 session，再创建今天的新 session。
- 后台线程会按 `TASK_SCAN_INTERVAL_SECONDS` 扫描超时 open session，写入或执行 `auto_end_session` 任务。
- 自动结束流程会更新 session、生成/复用 summary、写入去重 memory、记录 `session_task_history`，并生成一个默认 Markdown 交接文档。
- 同一 session 的 summary、memory 和默认 handoff document 都是幂等处理。

## 交接文档

生成 Markdown：

```bash
curl -X POST http://127.0.0.1:8000/handoff/generate/{session_id} \
  -H "Content-Type: application/json" \
  -d "{\"format\":\"markdown\",\"regenerate\":false}"
```

生成 JSON：

```bash
curl -X POST http://127.0.0.1:8000/handoff/generate/{session_id} \
  -H "Content-Type: application/json" \
  -d "{\"format\":\"json\",\"regenerate\":false}"
```

按用户导出 Markdown 交接文档：

```bash
curl http://127.0.0.1:8000/handoff/export/user/{user_id}?format=markdown
```

这个接口只需要 `user_id`。它导出的不是单次 session 文档，而是用户级交接材料：长期画像、咨询计划表、最近多次咨询摘要、长期记忆候选、最近消息线索和风险评估。它不会复制完整聊天记录。

返回字段包括：`document_id`、`session_id`、`user_id`、`format`、`content`、`download_url`、`file_path`、`created_at`。

当前 MVP 支持 `markdown` 和 `json`。`docx`、`pdf` 暂未实现。`/handoff/export/{document_id}` 当前直接返回 Markdown/JSON 内容并带下载响应头。

## 咨询质量规则

- 低内容 session：用户有效消息少于 2 条、总字数少于 20 个中文字符、只有“你好/在吗/嗯/好/随便”等寒暄，或没有具体困扰、事件、情绪、行为、计划、风险表达时，系统会标记 `is_low_content=true`、`summary_type=low_content`。
- 低内容 session 默认不生成正式咨询总结、长期记忆和正式交接文档，只记录跳过原因。确实需要查看时，可调用 `POST /handoff/generate/{session_id}` 并传入 `include_low_content=true`，此时内容会明确标注“内容不足”，不会伪装成正式咨询交接。
- 长期记忆只保存可复用事实、明确偏好、持续目标、风险线索和用户原话证据；寒暄、空泛总结、助手输出、无证据强解释标签会被跳过。
- 交接文档区分事实和待验证假设：事实来自用户表达或明确记录；假设必须标注证据和置信度，供心理咨询师复核，不作为诊断结论。
- 用户级导出接口 `GET /handoff/export/user/{user_id}` 面向转介/交接场景，会汇总最近多次 session、长期画像、计划表、长期记忆和风险记录，不只取最近第一次对话。

## Dify HTTP Request 配置

建议在 Dify 中配置这些 HTTP Request 节点：

- 开始前检查：`GET {BACKEND_URL}/session/status/{{user_id}}`
- 保存消息：`POST {BACKEND_URL}/session-message`
- 保存总结：`POST {BACKEND_URL}/session-summary`
- 保存长期记忆：`POST {BACKEND_URL}/memory`
- 读取上下文：`GET {BACKEND_URL}/context/{{user_id}}`
- 结束 session：`POST {BACKEND_URL}/session/finalize`
- 生成交接文档：`POST {BACKEND_URL}/handoff/generate/{{session_id}}`

分支建议：

- `session_stage in ["trust", "deep", "reframe", "action"]`：继续咨询。
- `session_stage == "ending"`：进入收束和小行动计划。
- `session_stage == "ended"`：停止本次咨询，保存总结和交接材料。
- `daily_limit_reached == true`：提示明天再开始正式咨询。

为了避免 Dify 布尔判断异常，接口同时返回 `is_new_session` 和 `is_new_session_str`。

## curl 示例

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/session/status/demo_user
curl http://127.0.0.1:8000/context/demo_user
```

保存消息：

```bash
curl -X POST http://127.0.0.1:8000/session-message \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"demo_user\",\"session_id\":\"SESSION_ID\",\"role\":\"user\",\"content\":\"最近工作压力很大\"}"
```

结束 session：

```bash
curl -X POST http://127.0.0.1:8000/session/finalize \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"demo_user\",\"session_id\":\"SESSION_ID\"}"
```

## 测试

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_mvp
```

测试覆盖：

- 新用户第一次访问 `/session/status/{user_id}`
- 用户当天已有 open session
- open session 超过 50 分钟自动结束
- 昨天 open session 今天访问时自动结束
- 自动扫描任务不会重复结束同一 session
- memory 不会重复写入
- handoff document 可以生成 Markdown
- handoff document 可以生成 JSON
- PostgreSQL `DATABASE_URL` 配置能被读取
- `/health` 能正常返回

## 部署

### Render / Railway

1. 创建 PostgreSQL 数据库。
2. 设置环境变量 `DATABASE_URL`、`APP_ENV=production`、`SESSION_LIMIT_MINUTES=50`。
3. 构建命令：`pip install -r requirements.txt`。
4. 启动命令：`uvicorn app.main:app --host 0.0.0.0 --port $PORT`。
5. 首次启动会自动初始化数据库。

### VPS

1. 安装 Python 3.11。
2. 配置 `.env` 或系统环境变量。
3. 运行 `pip install -r requirements.txt`。
4. 使用 systemd/supervisor 启动 `uvicorn app.main:app --host 0.0.0.0 --port 8000`。
5. 使用 Nginx/HTTPS 反向代理。

### Docker

```bash
docker build -t ai-psy-assistant-memory .
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:password@host:5432/dbname \
  -e APP_ENV=production \
  ai-psy-assistant-memory
```

## 日志和异常

服务使用结构化风格日志记录 session 创建、状态查询、自动结束、memory 写入、handoff 生成和任务扫描。普通日志不输出完整咨询原文。接口异常返回稳定 JSON，不直接暴露 Python 堆栈给调用方。

## 隐私和安全

- 高危关键词包括：`不想活了`、`想死`、`自杀`、`活着没意义`、`伤害自己`、`伤害别人`。
- 检测到高危表达时会标记 `risk_level=high`，并在交接文档风险评估中提示人工复核。
- 交接文档是结构化摘要，不是完整聊天记录复制。
- 当前项目没有登录/鉴权系统，公开上线前必须增加鉴权。
- 生产环境需要补充用户授权、数据查看、删除、导出和留存策略。

## 上线前检查清单

- PostgreSQL 可连接，`/health` 返回 `database.ok=true`。
- `DATABASE_URL` 不含硬编码真实密码。
- Dify HTTP Request 节点字段映射已验证。
- 公开环境已加鉴权。
- 高危内容处理和人工兜底流程已确认。
- 日志不包含完整咨询原文。
- 备份、迁移和数据删除策略已确认。
- 运行 `python -m unittest tests.test_mvp` 通过。

## 已知限制

- 交接文档的总结目前基于已保存 summary/messages 生成规则化草稿，不调用外部 LLM 做深度临床总结。
- 当前只支持 Markdown 和 JSON 导出。
- 后台任务是 FastAPI 进程内线程，未来多实例生产环境建议迁移到 Celery/APScheduler/独立 worker。
- 数据库初始化采用轻量 `init_db()`，复杂版本迁移建议后续引入 Alembic。
- 当前无登录鉴权，不适合直接公开给不受控用户访问。
