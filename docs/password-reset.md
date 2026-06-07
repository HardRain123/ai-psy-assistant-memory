# 邮箱验证与自助重置密码

本功能允许用户绑定并验证邮箱，然后通过已验证邮箱自助重置密码。浏览器只访问 Next 页面和 Next API，Next 服务端再通过 `BACKEND_SHARED_TOKEN` 调用 FastAPI 内部接口。

## 环境变量

FastAPI 需要配置：

```text
PASSWORD_RESET_TTL_MINUTES=30
PASSWORD_RESET_COOLDOWN_SECONDS=120
EMAIL_VERIFICATION_TTL_HOURS=24
TOKEN_RETENTION_DAYS=7
ACCOUNT_RATE_LIMIT_WINDOW_SECONDS=900
ACCOUNT_RATE_LIMIT_MAX_REQUESTS=5
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=no-reply@example.com
APP_BASE_URL=https://your-app.example.com
```

Next 需要配置：

```text
FASTAPI_INTERNAL_URL=http://127.0.0.1:8000
BACKEND_SHARED_TOKEN=<same-as-fastapi>
```

`APP_BASE_URL` 是用户在浏览器中访问前端的地址。邮件链接格式为：

```text
{APP_BASE_URL}/reset-password?token=...
{APP_BASE_URL}/verify-email?token=...
```

## 安全行为

- `users.email` 保存规范化后的小写邮箱，并设置唯一索引。
- 旧的无邮箱用户仍可用账号和密码登录，但需要先在 `/settings/account` 绑定并验证邮箱后才能通过邮箱找回密码。
- `password_reset_tokens` 只保存 `token_hash`，不保存原始 token。
- `email_verification_tokens` 只保存 `token_hash`，不保存原始 token。
- token 默认 30 分钟有效，确认成功后会标记 `used_at`。
- 邮箱验证 token 默认 24 小时有效，验证成功后写入 `users.email_verified_at`。
- 密码重置和邮箱验证都会先写 token 与 `email_outbox`，再尝试同进程发信。
- `email_outbox.body_text` 只保存 `{RESET_LINK}` 或 `{VERIFY_LINK}` 占位符，不保存原始 token 链接。
- 邮件发送失败只记录稳定错误类型，不把 SMTP 异常原文返回前端。
- 密码重置成功后会撤销该用户所有旧 `auth_sessions`。
- 只有已验证邮箱会收到密码重置邮件；无邮箱、邮箱不存在或未验证时，请求重置接口仍返回同一提示。
- 过期或已使用超过 `TOKEN_RETENTION_DAYS` 的重置和验证 token 会在账号相关请求中清理。
- 账号安全事件会记录操作类型、用户、邮箱 hash、IP hash、UA 和结果，不记录原始密码、原始 token 或密钥。
- 邮箱验证和密码重置请求会按操作类型、邮箱 hash、IP hash 做持久化限流；命中限流时仍返回稳定提示。
- SMTP、数据库或 token 校验异常不会把异常原文、traceback、共享 token、Dify Key 或 SMTP 密码返回给浏览器。

## 页面与接口

- `/forgot-password`：提交邮箱后始终显示稳定提示。
- `/reset-password?token=...`：校验一次性重置 token 后设置新密码。
- `/settings/account`：查看账号、邮箱状态，绑定/重发验证邮件，修改密码，退出全部设备。
- `/verify-email?token=...`：校验邮箱验证 token。
