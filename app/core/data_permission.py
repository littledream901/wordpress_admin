from tortoise.expressions import Q

from app.models.admin import DeptClosure, Role, RoleDataScope, User
from app.models.enums import DataScope


class DataPermissionFilter:
    """数据权限过滤器

    根据用户角色中定义的数据权限范围，生成 Tortoise ORM 的 Q 过滤条件。
    用户拥有多个角色时，取最宽松的权限范围。

    支持两种模式：
    1. 全局 data_scope（兼容旧版，未配置 resource 级权限时回退）
    2. 按业务模块 resource 级 data_scope（优先使用）

    用法:
        data_filter = await DataPermissionFilter.get_filter_condition(
            current_user, model, resource="site", owner_field="create_by", dept_field="dept_id"
        )
        items = await SomeModel.filter(data_filter).all()
    """

    @classmethod
    async def get_filter_condition(
        cls,
        current_user: User,
        model,
        resource: str | None = None,
        owner_field: str = "owner_id",
        dept_field: str = "dept_id",
    ) -> Q:
        """返回数据权限过滤条件

        Args:
            current_user: 当前登录用户
            model: 目标模型
            resource: 业务模块标识（如 site/account/gmail），用于查询 RoleDataScope
            owner_field: 数据所属人字段名
            dept_field: 数据所属部门字段名

        Returns:
            Q 对象，可直接用于 filter()
        """
        if current_user.is_superuser:
            return Q()  # 超管：查看全部数据

        roles: list[Role] = await current_user.roles
        if not roles:
            return Q(id=0)  # 无角色：看不到任何数据

        # 优先使用按业务模块的 data_scope
        if resource:
            scope_objs = await RoleDataScope.filter(
                role_id__in=[r.id for r in roles],
                resource=resource,
            ).prefetch_related("custom_depts")

            if scope_objs:
                return await cls._build_condition(scope_objs, current_user, owner_field, dept_field)

        # 回退到角色全局 data_scope
        return await cls._build_role_condition(roles, current_user, owner_field, dept_field)

    @classmethod
    async def _build_condition(cls, scope_objs, current_user, owner_field, dept_field) -> Q:
        """基于 RoleDataScope 对象列表构建 Q"""
        scopes = sorted([s.data_scope for s in scope_objs])
        best_scope = scopes[0]

        if best_scope == DataScope.ALL:
            return Q()

        if best_scope == DataScope.DEPT_AND_CHILD:
            if current_user.dept_id is None:
                return Q(**{owner_field: current_user.id})
            dept_ids = await DeptClosure.filter(
                ancestor=current_user.dept_id
            ).values_list("descendant", flat=True)
            dept_ids = list(dept_ids)
            dept_ids.append(current_user.dept_id)
            return Q(**{f"{dept_field}__in": dept_ids})

        if best_scope == DataScope.DEPT_ONLY:
            if current_user.dept_id is None:
                return Q(**{owner_field: current_user.id})
            return Q(**{dept_field: current_user.dept_id})

        if best_scope == DataScope.SELF_ONLY:
            return Q(**{owner_field: current_user.id})

        if best_scope == DataScope.CUSTOM:
            custom_dept_ids = set()
            for scope_obj in scope_objs:
                if scope_obj.data_scope == DataScope.CUSTOM:
                    dept_ids = await scope_obj.custom_depts.all().values_list("id", flat=True)
                    custom_dept_ids.update(dept_ids)
            if not custom_dept_ids:
                return Q(**{owner_field: current_user.id})
            return Q(**{f"{dept_field}__in": list(custom_dept_ids)})

        return Q(**{owner_field: current_user.id})

    @classmethod
    async def _build_role_condition(cls, roles, current_user, owner_field, dept_field) -> Q:
        """基于 Role 的全局 data_scope 构建 Q（兼容旧版）"""
        scopes = sorted([r.data_scope for r in roles])
        scope = scopes[0]

        if scope == DataScope.ALL:
            return Q()

        elif scope == DataScope.DEPT_AND_CHILD:
            if current_user.dept_id is None:
                return Q(**{owner_field: current_user.id})
            dept_ids = await DeptClosure.filter(
                ancestor=current_user.dept_id
            ).values_list("descendant", flat=True)
            dept_ids = list(dept_ids)
            dept_ids.append(current_user.dept_id)
            return Q(**{f"{dept_field}__in": dept_ids})

        elif scope == DataScope.DEPT_ONLY:
            if current_user.dept_id is None:
                return Q(**{owner_field: current_user.id})
            return Q(**{dept_field: current_user.dept_id})

        elif scope == DataScope.SELF_ONLY:
            return Q(**{owner_field: current_user.id})

        elif scope == DataScope.CUSTOM:
            custom_dept_ids = []
            for role in roles:
                depts = await role.custom_depts.all().values_list("id", flat=True)
                custom_dept_ids.extend(depts)
            custom_dept_ids = list(set(custom_dept_ids))
            if not custom_dept_ids:
                return Q(**{owner_field: current_user.id})
            return Q(**{f"{dept_field}__in": custom_dept_ids})

        return Q(**{owner_field: current_user.id})
