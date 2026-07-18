"""回收站 API — 查看、恢复、彻底删除已软删除的数据"""
from fastapi import APIRouter, Query

from app.controllers.account import account_controller
from app.controllers.ads_manager import ads_env_controller
from app.controllers.config_provider import provider_controller
from app.controllers.gmail_account import gmail_account_controller
from app.controllers.site_pipeline import site_controller
from app.schemas.base import Success, SuccessExtra
from app.schemas.recycle_bin import RecycleBinAction, RecycleBinEmpty, RecycleBinType

router = APIRouter(tags=["回收站"])

# 类型 → 控制器的映射
_CONTROLLER_MAP = {
    RecycleBinType.site: site_controller,
    RecycleBinType.gmail: gmail_account_controller,
    RecycleBinType.account: account_controller,
    RecycleBinType.provider: provider_controller,
    RecycleBinType.ads: ads_env_controller,
}

# 类型 → 显示名称映射
_TYPE_LABELS = {
    RecycleBinType.site: "站点",
    RecycleBinType.gmail: "Gmail账号",
    RecycleBinType.account: "账号",
    RecycleBinType.provider: "配置提供者",
    RecycleBinType.ads: "ADS账号",
}


def _get_summary_row(obj_dict: dict, item_type: RecycleBinType) -> str:
    """从对象字典中提取摘要信息"""
    if item_type == RecycleBinType.site:
        return obj_dict.get("domain", "")
    elif item_type == RecycleBinType.gmail:
        return obj_dict.get("username", "")
    elif item_type == RecycleBinType.account:
        return f"[{obj_dict.get('account_type', '')}] {obj_dict.get('username', '')}"
    elif item_type == RecycleBinType.provider:
        return f"[{obj_dict.get('provider_type', '')}] {obj_dict.get('provider_name', '')}"
    elif item_type == RecycleBinType.ads:
        return f"[{obj_dict.get('ads_env_id', '')}] {obj_dict.get('domain', '')}"
    return ""


@router.get("/list", summary="回收站列表")
async def recycle_bin_list(
    type: RecycleBinType = Query(..., description="数据类型"),
    page: int = Query(1),
    page_size: int = Query(10),
    keyword: str = Query(""),
):
    ctrl = _CONTROLLER_MAP[type]

    total, objs = await ctrl.list_deleted(page=page, page_size=page_size, order=["-deleted_at"])

    data = []
    for obj in objs:
        d = await obj.to_dict()
        d["resource_type"] = type.value
        d["resource_label"] = _TYPE_LABELS.get(type, type.value)
        d["summary"] = _get_summary_row(d, type)
        data.append(d)

    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post("/restore", summary="恢复数据")
async def recycle_bin_restore(payload: RecycleBinAction):
    ctrl = _CONTROLLER_MAP[payload.type]
    label = _TYPE_LABELS.get(payload.type, payload.type.value)

    obj = await ctrl.get_or_none(id=payload.id)
    if not obj:
        return Success(msg=f"该{label}不存在或已被彻底删除")

    await ctrl.restore(id=payload.id)
    return Success(msg=f"{label}已恢复")


@router.post("/permanent-delete", summary="彻底删除")
async def recycle_bin_permanent_delete(payload: RecycleBinAction):
    ctrl = _CONTROLLER_MAP[payload.type]
    label = _TYPE_LABELS.get(payload.type, payload.type.value)

    obj = await ctrl.get_or_none(id=payload.id)
    if not obj:
        return Success(msg=f"该{label}不存在或已被彻底删除")

    await ctrl.remove(id=payload.id)
    return Success(msg=f"{label}已彻底删除")


@router.post("/empty", summary="清空回收站")
async def recycle_bin_empty(payload: RecycleBinEmpty):
    ctrl = _CONTROLLER_MAP[payload.type]
    label = _TYPE_LABELS.get(payload.type, payload.type.value)

    deleted_count = await ctrl.model.filter(is_deleted=True).delete()
    return Success(data={"deleted": deleted_count}, msg=f"已清空 {deleted_count} 条{label}记录")
