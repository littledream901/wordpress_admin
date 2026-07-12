from pydantic import BaseModel, Field
from typing import Optional


class OperationJobCreate(BaseModel):
    resource_type: str = Field(..., description="资源类型")
    resource_id: int = Field(..., description="资源ID")
    domain: Optional[str] = Field("", description="关联域名")
    action_type: str = Field(..., description="操作类型")
    payload_json: Optional[str] = Field("{}", description="任务负载(JSON)")
    batch_id: Optional[str] = Field("", description="批次ID")


class OperationJobUpdate(BaseModel):
    id: int = Field(..., description="任务ID")
    status: Optional[str] = Field(None, description="任务状态")
    step: Optional[int] = Field(None, description="当前步骤")
    result_json: Optional[str] = Field(None, description="任务结果(JSON)")
    error_message: Optional[str] = Field(None, description="错误信息")
    worker_name: Optional[str] = Field(None, description="执行节点")


class BatchOperationCreate(BaseModel):
    resource_type: str = Field(..., description="资源类型 (site/gmail/shopify_source/shopify_product)")
    resource_ids: list[int] = Field(..., description="资源ID列表")
    action_type: str = Field(..., description="操作类型")
    domains: Optional[list[str]] = Field(None, description="关联域名列表")
    payload: Optional[dict] = Field(None, description="附加参数")
