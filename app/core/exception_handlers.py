"""FastAPI 异常处理器 —— 仅服务端使用，Agent 不依赖"""

from typing import Any

from fastapi.exceptions import HTTPException, RequestValidationError, ResponseValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from tortoise.exceptions import DoesNotExist, IntegrityError

from app.core.exceptions import (
    ErrorCode,
    ExternalAPIError,
    ProviderConfigError,
    ResourceBusyError,
)


def _error_response(
    exc: Any,
    http_code: int,
    msg: str = "",
    data: dict = None,
) -> JSONResponse:
    """统一 JSON 响应格式"""
    error_code = getattr(exc, "error_code", None)
    content = {
        "code": http_code,
        "error_code": error_code.value if isinstance(error_code, ErrorCode) else None,
        "msg": msg or str(exc),
    }
    if data:
        content["data"] = data
    return JSONResponse(content=content, status_code=http_code)


async def DoesNotExistHandle(req: Request, exc: DoesNotExist) -> JSONResponse:
    content = dict(code=404, error_code=ErrorCode.NOT_FOUND.value, msg=f"资源不存在: {exc}")
    return JSONResponse(content=content, status_code=404)


async def IntegrityHandle(_: Request, exc: IntegrityError) -> JSONResponse:
    content = dict(code=500, error_code=ErrorCode.INTEGRITY_ERROR.value, msg=f"数据完整性错误: {exc}")
    return JSONResponse(content=content, status_code=500)


async def HttpExcHandle(_: Request, exc: HTTPException) -> JSONResponse:
    content = dict(code=exc.status_code, error_code=None, msg=exc.detail, data=None)
    return JSONResponse(content=content, status_code=exc.status_code)


async def RequestValidationHandle(_: Request, exc: RequestValidationError) -> JSONResponse:
    content = dict(code=422, error_code=ErrorCode.VALIDATION_ERROR.value, msg=f"请求参数校验失败: {exc}")
    return JSONResponse(content=content, status_code=422)


async def ResponseValidationHandle(_: Request, exc: ResponseValidationError) -> JSONResponse:
    content = dict(code=500, error_code=ErrorCode.INTEGRITY_ERROR.value, msg=f"响应校验失败: {exc}")
    return JSONResponse(content=content, status_code=500)


async def ServiceErrorHandle(_: Request, exc: ExternalAPIError) -> JSONResponse:
    return _error_response(exc, 502,
        msg=str(exc),
        data={"provider": exc.provider, "action": exc.action},
    )


async def ResourceBusyHandle(_: Request, exc: ResourceBusyError) -> JSONResponse:
    return _error_response(exc, 409, msg=str(exc))


async def ProviderConfigErrorHandle(_: Request, exc: ProviderConfigError) -> JSONResponse:
    return _error_response(exc, 500,
        msg=str(exc),
        data={"provider": exc.provider, "key": exc.key},
    )
