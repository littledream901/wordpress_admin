from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import DataScope

# 业务模块标识 → 显示名称
RESOURCE_LABELS = {
    "site": "站点管理",
    "account": "账户配置",
    "gmail": "Gmail",
    "shopify": "Shopify",
    "operation": "操作任务",
    "import": "导入管理",
}


class RoleDataScopeSchema(BaseModel):
    id: int | None = None
    resource: str
    data_scope: DataScope = DataScope.SELF_ONLY
    custom_dept_ids: list[int] = []


class BaseRole(BaseModel):
    id: int
    name: str
    desc: str = ""
    data_scope: DataScope = DataScope.SELF_ONLY
    data_scopes: Optional[list] = []
    users: Optional[list] = []
    menus: Optional[list] = []
    apis: Optional[list] = []
    custom_depts: Optional[list] = []
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class RoleCreate(BaseModel):
    name: str = Field(json_schema_extra={"example": "管理员"})
    desc: str = Field("", json_schema_extra={"example": "管理员角色"})
    data_scope: DataScope = Field(DataScope.SELF_ONLY, json_schema_extra={"example": 3})


class RoleUpdate(BaseModel):
    id: int = Field(json_schema_extra={"example": 1})
    name: str = Field(json_schema_extra={"example": "管理员"})
    desc: str = Field("", json_schema_extra={"example": "管理员角色"})
    data_scope: DataScope = Field(DataScope.SELF_ONLY, json_schema_extra={"example": 3})


class RoleUpdateMenusApis(BaseModel):
    id: int
    menu_ids: Optional[list[int]] = None
    api_infos: Optional[list[dict]] = None
    data_scope: DataScope | None = None
    custom_dept_ids: list[int] | None = None
    data_scopes: list[RoleDataScopeSchema] | None = None
