from pydantic import BaseModel, Field
from typing import Optional


class ConfigProviderCreate(BaseModel):
    provider_type: str = Field(..., description="提供者类型")
    provider_name: str = Field(..., description="名称")
    description: Optional[str] = Field("", description="描述")
    remark: Optional[str] = Field("", description="备注")
    status: Optional[str] = Field("active", description="状态")
    is_default: Optional[bool] = Field(False, description="是否默认")
    priority: Optional[int] = Field(0, description="优先级")
    tags: Optional[str] = Field("", description="标签")


class ConfigProviderUpdate(BaseModel):
    id: int = Field(..., description="Provider ID")
    provider_name: Optional[str] = Field(None, description="名称")
    description: Optional[str] = Field(None, description="描述")
    remark: Optional[str] = Field(None, description="备注")
    status: Optional[str] = Field(None, description="状态")
    is_default: Optional[bool] = Field(None, description="是否默认")
    priority: Optional[int] = Field(None, description="优先级")
    tags: Optional[str] = Field(None, description="标签")


class ProviderConfigItemCreate(BaseModel):
    provider_id: int = Field(..., description="Provider ID")
    config_key: str = Field(..., description="配置键名")
    config_value: str = Field("", description="配置值")
    config_type: Optional[str] = Field("string", description="值类型")
    is_secret: Optional[bool] = Field(False, description="是否敏感")
    is_required: Optional[bool] = Field(False, description="是否必填")
    description: Optional[str] = Field("", description="描述")
    remark: Optional[str] = Field("", description="备注")
    sort: Optional[int] = Field(0, description="排序")


class ProviderConfigItemUpdate(BaseModel):
    id: int = Field(..., description="配置项ID")
    config_value: Optional[str] = Field(None, description="配置值")
    config_type: Optional[str] = Field(None, description="值类型")
    is_secret: Optional[bool] = Field(None, description="是否敏感")
    is_required: Optional[bool] = Field(None, description="是否必填")
    description: Optional[str] = Field(None, description="描述")
    remark: Optional[str] = Field(None, description="备注")
    sort: Optional[int] = Field(None, description="排序")


class ResourceProviderBindingCreate(BaseModel):
    resource_type: str = Field(..., description="资源类型")
    resource_id: int = Field(..., description="资源ID")
    provider_type: str = Field(..., description="提供者类型")
    provider_id: int = Field(..., description="Provider ID")
    bind_type: Optional[str] = Field("preferred", description="绑定类型")
    remark: Optional[str] = Field("", description="备注")


class BatchSaveItemsRequest(BaseModel):
    provider_id: int = Field(..., description="Provider ID")
    items: list[ProviderConfigItemCreate] = Field(..., description="配置项列表")


class BatchBindingRequest(BaseModel):
    site_ids: list[int] = Field(..., description="站点ID列表")
    provider_type: str = Field(..., description="Provider类型")
    provider_ids: list[int] = Field(..., description="Provider ID列表")
    bind_type: Optional[str] = Field("preferred", description="绑定类型")
    remark: Optional[str] = Field("", description="备注")
