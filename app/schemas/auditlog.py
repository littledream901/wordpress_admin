"""审计日志 Schema"""
from pydantic import BaseModel, Field


class AuditLogCreate(BaseModel):
    user_id: int = Field(0, description="用户ID")
    username: str = Field("", description="用户名称")
    module: str = Field("", description="功能模块")
    summary: str = Field("", description="请求描述")
    method: str = Field("", description="请求方法")
    path: str = Field("", description="请求路径")
    status: int = Field(-1, description="状态码")
    response_time: int = Field(0, description="响应时间(ms)")
    request_args: dict | None = Field(None, description="请求参数")
    response_body: dict | None = Field(None, description="返回数据")


class AuditLogUpdate(BaseModel):
    id: int
