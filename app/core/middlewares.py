import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.dependency import decode_token_lightweight
from app.log.log import set_trace_id
from app.models.admin import AuditLog

logger = logging.getLogger(__name__)

from .bgtask import BgTasks


class SimpleBaseMiddleware:
    """精简 ASGI 中间件基类。

    提供 before_request / after_request 钩子，不干扰 ASGI 标准调用链。
    子类无需直接操作 scope/receive/send。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        status_code = [200]

        async def _send(message):
            if message["type"] == "http.response.start":
                status_code[0] = message["status"]
            await send(message)

        await self.before_request(request)
        await self.app(scope, receive, _send)
        await self.after_request(request, status_code[0])

    async def before_request(self, request: Request):
        pass

    async def after_request(self, request: Request, status_code: int = 0):
        pass


class TraceIDMiddleware(SimpleBaseMiddleware):
    """为每个 HTTP 请求注入 trace_id，并设置到响应头 X-Trace-ID"""

    async def before_request(self, request: Request):
        tid = request.headers.get("X-Trace-ID") or str(uuid.uuid4())[:12]
        set_trace_id(tid)
        request.state.trace_id = tid
        request.state.start_time = datetime.now()

    async def after_request(self, request: Request, status_code: int = 0):
        pass


class AccessLogMiddleware(SimpleBaseMiddleware):
    """结构化访问日志 —— 记录 method、path、status、duration、trace_id、user_id。

    依赖 TraceIDMiddleware 先执行（注入 trace_id 和 start_time）。
    使用轻量级 JWT 解码获取 user_id，避免重复数据库查询。
    """

    # 跳过日志的路径前缀（健康检查等）
    SKIP_PREFIXES: tuple = ("/health",)

    async def before_request(self, request: Request):
        pass

    async def after_request(self, request: Request, status_code: int = 0):
        if request.url.path.startswith(self.SKIP_PREFIXES):
            return

        start_time: datetime = getattr(request.state, "start_time", datetime.now())
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        user_id = 0
        try:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                payload = decode_token_lightweight(token)
                if payload:
                    user_id = payload.get("user_id", 0)
        except Exception:
            pass

        loguru_logger.bind(trace_id=getattr(request.state, "trace_id", "-")).info(
            f"{request.method} {request.url.path} -> {status_code} ({duration_ms}ms)",
            access={
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "duration_ms": duration_ms,
                "user_id": user_id,
                "client_ip": request.client.host if request.client else "",
            },
        )


# 延迟 import 避免循环依赖
from loguru import logger as loguru_logger


class BackGroundTaskMiddleware(SimpleBaseMiddleware):
    async def before_request(self, request):
        await BgTasks.init_bg_tasks_obj()

    async def after_request(self, request, status_code: int = 0):
        await BgTasks.execute_tasks()


class HttpAuditLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, methods: list[str], exclude_paths: list[str]):
        super().__init__(app)
        self.methods = methods
        self.exclude_paths = exclude_paths
        self.audit_log_paths = ["/api/v1/auditlog/list"]
        self.max_body_size = 1024 * 1024  # 1MB 响应体大小限制

    async def get_request_args(self, request: Request) -> dict:
        args = {}
        # 获取查询参数
        for key, value in request.query_params.items():
            args[key] = value

        # 获取请求体
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    args.update(body)
                elif isinstance(body, list):
                    args["_body"] = body
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                # 只有非空请求体解析失败才告警（空 body 说明参数在 query string）
                body_bytes = await request.body()
                if body_bytes and body_bytes.strip():
                    logger.warning(
                        "审计日志解析请求体 JSON 失败: %s %s | err=%s",
                        request.method, request.url.path, e,
                    )
                # 不 fallback 到 form：JSON 解析失败说明 body 不是 JSON，不应猜测为 form
            except Exception:
                pass

        return args

    async def get_response_body(self, request: Request, response: Response) -> Any:
        # 检查Content-Length
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > self.max_body_size:
            return {"code": 0, "msg": "Response too large to log", "data": None}

        if hasattr(response, "body"):
            body = response.body
        else:
            body_chunks = []
            async for chunk in response.body_iterator:
                if not isinstance(chunk, bytes):
                    chunk = chunk.encode(response.charset)
                body_chunks.append(chunk)

            response.body_iterator = self._async_iter(body_chunks)
            body = b"".join(body_chunks)

        if any(request.url.path.startswith(path) for path in self.audit_log_paths):
            try:
                data = self.lenient_json(body)
                # 只保留基本信息，去除详细的响应内容
                if isinstance(data, dict):
                    data.pop("response_body", None)
                    if "data" in data and isinstance(data["data"], list):
                        for item in data["data"]:
                            item.pop("response_body", None)
                return data
            except Exception:
                return None

        return self.lenient_json(body)

    def lenient_json(self, v: Any) -> Any:
        if isinstance(v, (str, bytes)):
            try:
                return json.loads(v)
            except (ValueError, TypeError):
                pass
        return v

    async def _async_iter(self, items: list[bytes]) -> AsyncGenerator[bytes, None]:
        for item in items:
            yield item

    async def get_request_log(self, request: Request, response: Response) -> dict:
        """
        根据request和response对象获取对应的日志记录数据
        """
        data: dict = {"path": request.url.path, "status": response.status_code, "method": request.method}
        # 路由信息
        app: FastAPI = request.app
        for route in app.routes:
            if (
                isinstance(route, APIRoute)
                and route.path_regex.match(request.url.path)
                and request.method in route.methods
            ):
                data["module"] = ",".join(route.tags)
                data["summary"] = route.summary
        # 获取用户信息（轻量级 JWT 解码，不查数据库）
        data["user_id"] = 0
        data["username"] = ""
        try:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                payload = decode_token_lightweight(token)
                if payload:
                    data["user_id"] = payload.get("user_id", 0)
                    data["username"] = payload.get("username", "")
        except Exception:
            pass
        return data

    async def before_request(self, request: Request):
        request_args = await self.get_request_args(request)
        request.state.request_args = request_args

    async def after_request(self, request: Request, response: Response, process_time: int):
        if request.method in self.methods:
            for path in self.exclude_paths:
                if re.search(path, request.url.path, re.I) is not None:
                    return
            data: dict = await self.get_request_log(request=request, response=response)
            data["response_time"] = process_time

            data["request_args"] = request.state.request_args
            data["response_body"] = await self.get_response_body(request, response)
            await AuditLog.create(**data)

        return response

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 跳过排除路径（避免提前消费 multipart form data 导致文件上传失败）
        for path in self.exclude_paths:
            if re.search(path, request.url.path, re.I) is not None:
                return await call_next(request)

        start_time: datetime = datetime.now()
        await self.before_request(request)
        response = await call_next(request)
        end_time: datetime = datetime.now()
        process_time = int((end_time.timestamp() - start_time.timestamp()) * 1000)
        await self.after_request(request, response, process_time)
        return response
