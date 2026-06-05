# 第一步账号鉴权配置

本阶段实现最小安全闭环：浏览器只访问 Next；Next 服务端和 Dify 才能通过共享密钥访问 FastAPI 敏感接口。

## 环境变量

FastAPI 需要：

```text
AUTH_SECRET=一段足够长的随机字符串
BACKEND_SHARED_TOKEN=一段足够长的随机字符串
ADMIN_USERNAME=admin
ADMIN_PASSWORD=首次初始化管理员密码
SESSION_TTL_DAYS=7
```

Next 需要：

```text
FASTAPI_INTERNAL_URL=http://127.0.0.1:8000
BACKEND_SHARED_TOKEN=与 FastAPI 相同
DIFY_API_URL=https://api.dify.ai/v1
DIFY_API_KEY=你的 Dify App API Key
SESSION_TTL_DAYS=7
```

`BACKEND_SHARED_TOKEN` 只能存在于 FastAPI 环境变量、Next 服务端环境变量和 Dify HTTP Request header 中，不能出现在浏览器端代码或页面内容中。

## Dify HTTP Request Header

所有调用 FastAPI 的 Dify HTTP Request 节点都需要增加：

```text
X-Backend-Token: <BACKEND_SHARED_TOKEN>
```

至少包括这些接口：

- `/context/{user_id}`
- `/memory`
- `/session/status/{user_id}`
- `/session-message`
- `/session-summary`
- `/profile`
- `/session-transcript/{session_id}`
- `/care-plan`
- `/care-plan/{user_id}`
- `/session/finalize`

浏览器请求体不再传 `userId`；Next `/api/chat` 会从 HttpOnly 登录 session 取稳定 `user_id` 并传给 Dify。

## 管理员和邀请码

首次启动且数据库中没有管理员时，FastAPI 会使用 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 初始化管理员。已有管理员时不会覆盖密码。

管理员登录网页后可以生成、查看和撤销邀请码。原始邀请码只在创建成功时显示一次，数据库只保存 hash。
