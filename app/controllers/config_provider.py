"""Provider Controller"""
from app.core.crud import CRUDBase
from app.models.config_provider import ConfigProvider, ProviderConfigItem, ResourceProviderBinding
from app.models.site_pipeline import Site
from app.schemas.config_provider import (
    ConfigProviderCreate, ConfigProviderUpdate,
    ProviderConfigItemCreate, ProviderConfigItemUpdate,
    ResourceProviderBindingCreate,
)


class ConfigProviderController(CRUDBase[ConfigProvider, ConfigProviderCreate, ConfigProviderUpdate]):
    def __init__(self):
        super().__init__(model=ConfigProvider)

    async def get_by_type(self, provider_type: str):
        return await self.model.filter(provider_type=provider_type, status="active").order_by("-priority").all()

    async def _lock_bindings_for_default_change(self, provider_type: str, new_provider_id: int):
        """固定方案：切换默认 Provider 前，将隐式依赖旧默认的站点固化为显式绑定。

        所有没有显式绑定的站点，原本隐式使用当前默认 Provider。
        在默认 Provider 改变前，需要为这些站点创建显式绑定指向当前默认，
        这样以后即使默认变了，它们的绑定也不会漂移。
        """
        old_default = await self.model.filter(
            provider_type=provider_type, is_default=True, status="active"
        ).first()
        if not old_default or old_default.id == new_provider_id:
            return 0

        # 找出所有站点 ID
        all_site_ids = [s.id for s in await Site.all().only("id")]

        # 找出已有显式绑定的站点 ID
        existing_bindings = await ResourceProviderBinding.filter(
            resource_type="site",
            provider_type=provider_type,
            resource_id__in=all_site_ids,
        ).only("resource_id")
        bound_site_ids = {b.resource_id for b in existing_bindings}

        # 为无绑定的站点创建显式绑定 → 指向旧默认
        unbound_site_ids = [sid for sid in all_site_ids if sid not in bound_site_ids]
        count = 0
        for sid in unbound_site_ids:
            try:
                await ResourceProviderBinding.create(
                    resource_type="site",
                    resource_id=sid,
                    provider_type=provider_type,
                    provider_id=old_default.id,
                    bind_type="preferred",
                    remark=f"自动固化: 默认 {old_default.provider_name}",
                )
                count += 1
            except Exception:
                pass
        return count

    async def set_default(self, provider_id: int):
        """将指定 provider 设为该类型的默认

        切换默认前，先将无显式绑定的站点固化为绑定当前默认，防止后续漂移。
        """
        provider = await self.get(id=provider_id)
        if not provider:
            return
        await self._lock_bindings_for_default_change(provider.provider_type, provider_id)
        await self.model.filter(provider_type=provider.provider_type).update(is_default=False)
        await self.model.filter(id=provider_id).update(is_default=True)

    async def create(self, *, obj_in: ConfigProviderCreate):
        """创建 Provider：如果 is_default=True 则固化和取消同类型其他默认"""
        data = obj_in.model_dump()
        if data.get("is_default"):
            await self._lock_bindings_for_default_change(data["provider_type"], 0)
            await self.model.filter(provider_type=data["provider_type"]).update(is_default=False)
        return await super().create(obj_in=obj_in)

    async def update(self, *, id: int, obj_in: ConfigProviderUpdate):
        """更新 Provider：如果 is_default=True 则联动取消同类型其他默认，并固化绑定"""
        if obj_in.is_default and id:
            provider = await self.get(id=id)
            if provider:
                await self._lock_bindings_for_default_change(provider.provider_type, id)
                await self.model.filter(
                    provider_type=provider.provider_type
                ).exclude(id=id).update(is_default=False)
        return await super().update(id=id, obj_in=obj_in)


class ProviderConfigItemController(CRUDBase[ProviderConfigItem, ProviderConfigItemCreate, ProviderConfigItemUpdate]):
    def __init__(self):
        super().__init__(model=ProviderConfigItem)

    async def get_by_provider(self, provider_id: int):
        return await self.model.filter(provider_id=provider_id).order_by("sort").all()

    async def batch_save(self, provider_id: int, items: list[ProviderConfigItemCreate]):
        """批量保存配置项：存在则更新值，不存在则新增"""
        for item in items:
            existed = await self.model.filter(provider_id=provider_id, config_key=item.config_key).first()
            if existed:
                await self.model.filter(id=existed.id).update(
                    config_value=item.config_value,
                    description=item.description,
                    remark=item.remark or "",
                    config_type=item.config_type,
                    is_secret=item.is_secret,
                    is_required=item.is_required,
                    sort=item.sort,
                )
            else:
                await self.model.create(
                    provider_id=provider_id,
                    config_key=item.config_key,
                    config_value=item.config_value,
                    config_type=item.config_type or "string",
                    is_secret=item.is_secret or False,
                    is_required=item.is_required or False,
                    description=item.description or "",
                    remark=item.remark or "",
                    sort=item.sort or 0,
                )
        return len(items)


class ResourceProviderBindingController(CRUDBase[ResourceProviderBinding, ResourceProviderBindingCreate, dict]):
    def __init__(self):
        super().__init__(model=ResourceProviderBinding)

    async def get_for_resource(self, resource_type: str, resource_id: int):
        return await self.model.filter(resource_type=resource_type, resource_id=resource_id).all()


provider_controller = ConfigProviderController()
provider_item_controller = ProviderConfigItemController()
binding_controller = ResourceProviderBindingController()
