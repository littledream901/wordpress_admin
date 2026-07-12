from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field


class MenuType(StrEnum):
    CATALOG = "catalog"  # 目录
    MENU = "menu"  # 菜单


class BaseMenu(BaseModel):
    id: int
    name: str
    path: str
    remark: Optional[dict]
    menu_type: Optional[MenuType]
    icon: Optional[str]
    order: int
    parent_id: int
    is_hidden: bool
    component: str
    keepalive: bool
    redirect: Optional[str]
    children: Optional[list["BaseMenu"]]


class MenuCreate(BaseModel):
    menu_type: MenuType = Field(default=MenuType.CATALOG.value)
    name: str = Field(json_schema_extra={"example": "用户管理"})
    icon: Optional[str] = "ph:user-list-bold"
    path: str = Field(json_schema_extra={"example": "/system/user"})
    order: Optional[int] = Field(json_schema_extra={"example": 1})
    parent_id: Optional[int] = Field(default=0, json_schema_extra={"example": 0})
    is_hidden: Optional[bool] = False
    component: str = Field(default="Layout", json_schema_extra={"example": "/system/user"})
    keepalive: Optional[bool] = True
    redirect: Optional[str] = ""


class MenuUpdate(BaseModel):
    id: int
    menu_type: Optional[MenuType] = Field(json_schema_extra={"example": MenuType.CATALOG.value})
    name: Optional[str] = Field(json_schema_extra={"example": "用户管理"})
    icon: Optional[str] = "ph:user-list-bold"
    path: Optional[str] = Field(json_schema_extra={"example": "/system/user"})
    order: Optional[int] = Field(json_schema_extra={"example": 1})
    parent_id: Optional[int] = Field(json_schema_extra={"example": 0})
    is_hidden: Optional[bool] = False
    component: Optional[str] = None
    keepalive: Optional[bool] = False
    redirect: Optional[str] = ""
