from typing import List

from app.core.crud import CRUDBase
from app.models.admin import Api, Dept, Menu, Role, RoleDataScope
from app.schemas.roles import RoleCreate, RoleUpdate


class RoleController(CRUDBase[Role, RoleCreate, RoleUpdate]):
    def __init__(self):
        super().__init__(model=Role)

    async def is_exist(self, name: str) -> bool:
        return await self.model.filter(name=name).exists()

    async def update_roles(self, role: Role, menu_ids: List[int], api_infos: List[dict]) -> None:
        await role.menus.clear()
        for menu_id in menu_ids:
            menu_obj = await Menu.filter(id=menu_id).first()
            await role.menus.add(menu_obj)

        await role.apis.clear()
        for item in api_infos:
            api_obj = await Api.filter(path=item.get("path"), method=item.get("method")).first()
            await role.apis.add(api_obj)

    async def update_roles_full(
        self,
        role: Role,
        menu_ids: List[int],
        api_infos: List[dict],
        data_scope: int | None = None,
        custom_dept_ids: List[int] | None = None,
        data_scopes: List[dict] | None = None,
    ) -> None:
        """完整更新角色权限：菜单 + API + 数据权限（全局 + 按业务）"""
        await self.update_roles(role, menu_ids, api_infos)

        if data_scope is not None:
            role.data_scope = data_scope
            await role.save()

        if custom_dept_ids is not None:
            await role.custom_depts.clear()
            for dept_id in custom_dept_ids:
                dept_obj = await Dept.filter(id=dept_id).first()
                if dept_obj:
                    await role.custom_depts.add(dept_obj)

        # 按业务模块的数据权限
        if data_scopes is not None:
            # 删除旧配置
            await RoleDataScope.filter(role=role).delete()
            for item in data_scopes:
                scope_obj = await RoleDataScope.create(
                    role=role,
                    resource=item["resource"],
                    data_scope=item["data_scope"],
                )
                # 自定义部门
                dept_ids = item.get("custom_dept_ids") or []
                for dept_id in dept_ids:
                    dept_obj = await Dept.filter(id=dept_id).first()
                    if dept_obj:
                        await scope_obj.custom_depts.add(dept_obj)


role_controller = RoleController()
