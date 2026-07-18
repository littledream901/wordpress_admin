from fastapi.routing import APIRoute

from app.core.crud import CRUDBase
from app.log import logger
from app.models.admin import Api
from app.schemas.apis import ApiCreate, ApiUpdate

# 写入类方法 → 自动标记为按钮权限
_BUTTON_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


def _collect_api_routes(routes):
    """递归收集所有 APIRoute（处理 _IncludedRouter / Mount 等嵌套路由）"""
    result: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            result.append(route)
        # 嵌套子路由（_IncludedRouter / Router / Mount 都有 .routes）
        nested = getattr(route, 'routes', None)
        if nested is not None:
            result.extend(_collect_api_routes(nested))
        # Mount 可能通过 .app.routes 暴露
        nested_app = getattr(route, 'app', None)
        if nested_app is not None:
            nested_routes = getattr(nested_app, 'routes', None)
            if nested_routes is not None:
                result.extend(_collect_api_routes(nested_routes))
    return result


class ApiController(CRUDBase[Api, ApiCreate, ApiUpdate]):
    def __init__(self):
        super().__init__(model=Api)

    async def refresh_api(self):
        from app import app

        # 递归收集所有带鉴权的 API 路由
        all_routes = _collect_api_routes(app.routes)
        all_api_list = []
        for route in all_routes:
            if len(route.dependencies) > 0:
                method = list(route.methods)[0]
                path = route.path
                all_api_list.append((method, path))

        # 删除废弃的 API 数据
        for api in await Api.all():
            if (api.method, api.path) not in all_api_list:
                logger.debug(f"API Deleted {api.method} {api.path}")
                await api.delete()

        # 新增/更新 API
        for route in all_routes:
            if len(route.dependencies) > 0:
                method = list(route.methods)[0]
                path = route.path
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
