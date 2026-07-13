from fastapi import APIRouter, Query
from tortoise.expressions import Q

from app.controllers.account import account_controller
from app.schemas.base import Success, SuccessExtra
from app.schemas.account import AccountCreate, AccountUpdate

router = APIRouter(tags=["Account"])


@router.get("/list", summary="账号列表")
async def list_accounts(
    page: int = Query(1),
    page_size: int = Query(10),
    account_type: str = Query(""),
    username: str = Query(""),
    provider_id: int = Query(None, description="按 Provider 筛选"),
):
    q = Q()
    if account_type:
        q &= Q(account_type__contains=account_type)
    if username:
        q &= Q(username__contains=username)
    if provider_id:
        q &= Q(provider_id=provider_id)
    total, objs = await account_controller.list(page=page, page_size=page_size, search=q, order=["-id"])
    data = [await obj.to_dict() for obj in objs]
    # 补上 provider_name
    from app.models.config_provider import ConfigProvider
    provider_ids = list(set(d.get("provider_id") for d in data if d.get("provider_id")))
    provider_map = {}
    if provider_ids:
        providers = await ConfigProvider.filter(id__in=provider_ids).all()
        provider_map = {p.id: p.provider_name for p in providers}
    for d in data:
        d["provider_name"] = provider_map.get(d.get("provider_id"), "")
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post("/create", summary="新增账号")
async def create_account(payload: AccountCreate):
    await account_controller.create(payload)
    return Success(msg="Created Successfully")


@router.post("/update", summary="更新账号")
async def update_account(payload: AccountUpdate):
    await account_controller.update(id=payload.id, obj_in=payload)
    return Success(msg="Updated Successfully")


@router.delete("/delete", summary="删除账号")
async def delete_account(id: int = Query(..., description="账号ID")):
    await account_controller.remove(id=id)
    return Success(msg="Deleted Successfully")
