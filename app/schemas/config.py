from pydantic import BaseModel, Field
from typing import Optional


class ConfigCreate(BaseModel):
    name: str = Field(..., description="配置键名")
    value: str = Field("", description="配置值")
    description: Optional[str] = Field(None, description="配置说明")
    category: str = Field(..., description="配置分类")
    sort_order: int = Field(0, description="排序")
    is_secret: bool = Field(False, description="是否为敏感信息")
    is_enabled: bool = Field(True, description="是否启用")


class ConfigUpdate(BaseModel):
    id: int = Field(..., description="配置ID")
    name: Optional[str] = Field(None, description="配置键名")
    value: Optional[str] = Field(None, description="配置值")
    description: Optional[str] = Field(None, description="配置说明")
    category: Optional[str] = Field(None, description="配置分类")
    sort_order: Optional[int] = Field(None, description="排序")
    is_secret: Optional[bool] = Field(None, description="是否为敏感信息")
    is_enabled: Optional[bool] = Field(None, description="是否启用")
