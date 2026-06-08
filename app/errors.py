import logging

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)


ERROR_MESSAGES = {
    "admin_required": "没有管理员权限。",
    "authentication_required": "请先登录。",
    "backend_unavailable": "服务暂时不可用，请稍后再试。",
    "forbidden": "没有访问权限。",
    "invalid_credentials": "账号或密码不正确，请检查后再试。",
    "invalid_invite_code": "邀请码不存在，请检查后重新输入。",
    "invalid_request": "请求格式不正确。",
    "invalid_username": "账号需要 3-64 个字符，只能包含字母、数字、下划线、点、@ 或短横线。",
    "inactive_invite_code": "邀请码已被使用或已失效，请联系管理员重新生成。",
    "invite_not_found": "邀请码不存在。",
    "username_exists": "这个账号已经被注册，请换一个账号名。",
    "validation_error": "请求格式不正确。",
    "weak_password": "密码至少需要 8 个字符。",
    "email_exists": "这个邮箱已经被注册，请换一个邮箱。",
    "invalid_email": "请输入有效的邮箱地址。",
    "password_reset_invalid": "重置链接无效或已过期，请重新申请。",
    "password_reset_confirm_failed": "密码重置服务暂时不可用，请稍后再试。",
    "password_reset_request_failed": "如果邮箱存在，重置链接会发送到该邮箱。",
    "email_verification_invalid": "验证链接无效或已过期，请重新申请。",
    "email_verification_failed": "邮箱验证服务暂时不可用，请稍后再试。",
    "change_password_failed": "修改密码失败，请稍后再试。",
    "logout_all_failed": "退出全部设备失败，请稍后再试。",
    "care_plan_get_failed": "读取咨询计划失败，请稍后再试。",
    "care_plan_save_failed": "保存咨询计划失败，请稍后再试。",
    "context_get_failed": "读取上下文失败，请稍后再试。",
    "handoff_export_failed": "导出交接文档失败，请稍后再试。",
    "handoff_generate_failed": "生成交接文档失败，请稍后再试。",
    "handoff_read_failed": "读取交接文档失败，请稍后再试。",
    "memory_get_failed": "读取记忆失败，请稍后再试。",
    "memory_save_failed": "保存记忆失败，请稍后再试。",
    "profile_get_failed": "读取用户画像失败，请稍后再试。",
    "profile_save_failed": "保存用户画像失败，请稍后再试。",
    "session_finalize_failed": "结束会话失败，请稍后再试。",
    "session_message_save_failed": "保存会话消息失败，请稍后再试。",
    "session_start_failed": "开始会话失败，请稍后再试。",
    "session_status_failed": "读取会话状态失败，请稍后再试。",
    "session_summary_save_failed": "保存会话总结失败，请稍后再试。",
    "session_transcript_get_failed": "读取会话记录失败，请稍后再试。",
    "get_care_plan_failed": "读取咨询计划失败，请稍后再试。",
    "save_care_plan_failed": "保存咨询计划失败，请稍后再试。",
    "get_context_failed": "读取上下文失败，请稍后再试。",
    "export_handoff_failed": "导出交接文档失败，请稍后再试。",
    "export_handoff_for_user_failed": "导出交接文档失败，请稍后再试。",
    "generate_handoff_failed": "生成交接文档失败，请稍后再试。",
    "read_handoff_failed": "读取交接文档失败，请稍后再试。",
    "read_handoff_for_session_failed": "读取交接文档失败，请稍后再试。",
    "read_handoff_for_user_failed": "读取交接文档失败，请稍后再试。",
    "get_memory_failed": "读取记忆失败，请稍后再试。",
    "save_memory_failed": "保存记忆失败，请稍后再试。",
    "get_user_profile_failed": "读取用户画像失败，请稍后再试。",
    "save_user_profile_failed": "保存用户画像失败，请稍后再试。",
    "finalize_session_failed": "结束会话失败，请稍后再试。",
    "save_session_message_failed": "保存会话消息失败，请稍后再试。",
    "start_session_failed": "开始会话失败，请稍后再试。",
    "save_session_summary_failed": "保存会话总结失败，请稍后再试。",
    "get_session_transcript_failed": "读取会话记录失败，请稍后再试。",
    "admin_user_list_failed": "读取用户列表失败，请稍后再试。",
    "admin_user_export_failed": "导出用户数据失败，请稍后再试。",
    "admin_user_disable_failed": "停用账号失败，请稍后再试。",
    "admin_self_session_reset_failed": "重置会话失败，请稍后再试。",
    "session_not_found": "会话不存在。",
    "user_not_found": "用户不存在。",
    "cannot_disable_self": "不能停用当前登录的管理员账号。",
    "cannot_disable_admin": "不能停用管理员账号。",
    "debug_operation_failed": "调试操作失败，请稍后再试。",
    "db_health_failed": "数据库状态检查失败，请稍后再试。",
}


AUTH_ERROR_CODES = {
    "username must be 3-64 characters using letters, numbers, _ . @ or -": "invalid_username",
    "password must be at least 8 characters": "weak_password",
    "invite not found": "invite_not_found",
    "invalid invite code": "invalid_invite_code",
    "invite code is not active": "inactive_invite_code",
    "username already exists": "username_exists",
    "email already exists": "email_exists",
    "invalid email": "invalid_email",
    "password reset token invalid": "password_reset_invalid",
    "email verification token invalid": "email_verification_invalid",
    "invalid username or password": "invalid_credentials",
    "authentication required": "authentication_required",
    "admin access required": "admin_required",
}


def public_error(error: str, message: str | None = None, **extra) -> dict:
    payload = {
        "success": False,
        "error": error,
        "message": message or ERROR_MESSAGES.get(error, ERROR_MESSAGES["backend_unavailable"]),
    }
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


def json_error(status_code: int, error: str, message: str | None = None, **extra) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=public_error(error, message, **extra))


def auth_error_payload(message: str) -> dict:
    error = AUTH_ERROR_CODES.get(message, "invalid_request")
    return public_error(error)


def auth_error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=auth_error_payload(message))


def _http_error_code(exc: HTTPException) -> str:
    if isinstance(exc.detail, dict) and isinstance(exc.detail.get("error"), str):
        return exc.detail["error"]

    detail = exc.detail if isinstance(exc.detail, str) else ""
    if detail in AUTH_ERROR_CODES:
        return AUTH_ERROR_CODES[detail]

    if exc.status_code == 401:
        return "authentication_required"
    if exc.status_code == 403:
        return "forbidden"
    if exc.status_code == 503:
        return "backend_unavailable"
    if exc.status_code >= 500:
        return "backend_unavailable"
    return "invalid_request"


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and exc.detail.get("success") is False:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return json_error(exc.status_code, _http_error_code(exc))


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("request_validation_failed path=%s", request.url.path)
    return json_error(400, "validation_error")


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_request_failed path=%s", request.url.path)
    return json_error(500, "backend_unavailable")


def install_exception_handlers(app):
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
