import os
import smtplib
from email.message import EmailMessage

from app.config import APP_BASE_URL, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _smtp_port() -> int:
    raw_value = os.getenv("SMTP_PORT")
    if not raw_value:
        return SMTP_PORT
    try:
        return int(raw_value)
    except ValueError:
        return SMTP_PORT


def app_base_url() -> str:
    return _env("APP_BASE_URL", APP_BASE_URL or "http://localhost:3000").rstrip("/")


def send_email_message(to_email: str, subject: str, body_text: str, body_html: str = "") -> None:
    host = _env("SMTP_HOST", SMTP_HOST)
    from_email = _env("SMTP_FROM", SMTP_FROM)
    username = _env("SMTP_USER", SMTP_USER)
    password = _env("SMTP_PASSWORD", SMTP_PASSWORD)
    port = _smtp_port()

    if not host or not from_email:
        raise RuntimeError("smtp_unavailable")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email
    message.set_content(body_text)
    if body_html:
        message.add_alternative(body_html, subtype="html")

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
            if username or password:
                smtp.login(username, password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls()
        if username or password:
            smtp.login(username, password)
        smtp.send_message(message)


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    send_email_message(
        to_email,
        "重置你的密码",
        "\n".join(
            [
                "你正在重置 AI 情绪整理助手的登录密码。",
                "",
                "请在 30 分钟内打开下面的一次性链接完成重置：",
                reset_url,
                "",
                "如果这不是你本人操作，可以忽略这封邮件。",
            ]
        ),
    )


def send_email_verification_email(to_email: str, verify_url: str) -> None:
    send_email_message(
        to_email,
        "验证你的邮箱",
        "\n".join(
            [
                "请验证你在 AI 情绪整理助手使用的邮箱。",
                "",
                "请在 24 小时内打开下面的一次性链接完成验证：",
                verify_url,
                "",
                "如果这不是你本人操作，可以忽略这封邮件。",
            ]
        ),
    )
