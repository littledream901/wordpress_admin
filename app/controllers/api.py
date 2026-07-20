from fastapi.routing import APIRoute

from app.core.crud import CRUDBase
from app.log import logger
from app.models.admin import Api
from app.schemas.apis import ApiCreate, ApiUpdate

# 写入类方法 → 自动标记为按钮权限
_BUTTON_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


def _collect_api_routes(routes, parent_prefix: str = ""):
    """递归收集所有 APIRoute，同时拼接 Mount 前缀确保路径完整。

    Starlette 的 Mount 对象在 app.include_router(prefix="/api") 时会包裹子路由，
    子路由的 path 不包含 Mount 的 prefix。此函数递归时追踪并拼接前缀，
    确保最终 path 为完整路径（如 /api/v1/site-pipeline/site/create）。
    """
    result: list[tuple[APIRoute, str]] = []
    for route in routes:
        if isinstance(route, APIRoute):
            result.append((route, parent_prefix))
        # 获取当前路由的 Mount path（如 "/api" 或 "/v1"）
        mount_path = getattr(route, 'path', "") or ""
        new_prefix = parent_prefix + mount_path
        # 嵌套子路由（_IncludedRouter / Router / Mount 都有 .routes）
        nested = getattr(route, 'routes', None)
        if nested is not None:
            result.extend(_collect_api_routes(nested, new_prefix))
        # Mount 可能通过 .app.routes 暴露
        nested_app = getattr(route, 'app', None)
        if nested_app is not None:
            nested_routes = getattr(nested_app, 'routes', None)
            if nested_routes is not None:
                result.extend(_collect_api_routes(nested_routes, new_prefix))
    return result


class ApiController(CRUDBase[Api, ApiCreate, ApiUpdate]):
    def __init__(self):
        super().__init__(model=Api)

    async def refresh_api(self):
        from app import app

        # 递归收集所有带鉴权的 API 路由，prefix 确保路径完整含 /api 前缀
        all_routes = _collect_api_routes(app.routes)
        all_api_list = []
        for route, prefix in all_routes:
            if len(route.dependencies) > 0:
                method = list(route.methods)[0]
                path = prefix + route.path
                all_api_list.append((method, path))

        # 删除废弃的 API 数据
        for api in await Api.all():
            if (api.method, api.path) not in all_api_list:
                logger.debug(f"API Deleted {api.method} {api.path}")
                await api.delete()

        # 新增/更新 API
        for route, prefix in all_routes:
            if len(route.dependencies) > 0:
                method = list(route.methods)[0]
                path = prefix + route.path
                summary = route.summary or ""
                tags = list(route.tags)[0] if route.tags else "default"
                # 写入类方法自动标记为按钮权限，GET 只读不标记
                is_button = method in _BUTTON_METHODS
                api_obj = await Api.filter(method=method, path=path).first()
                if api_obj:
                    await api_obj.update_from_dict(dict(
                        method=method, path=path, summary=summary, tags=tags, is_button=is_button,
                    )).save()
                else:
                    logger.debug(f"API Created {method} {path}")
                    await Api.create(**dict(
                        method=method, path=path, summary=summary, tags=tags, is_button=is_button,
                    ))


api_controller = ApiController()
