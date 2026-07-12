from pydantic import BaseModel, Field
from typing import Optional


class ImportJobCreate(BaseModel):
    import_type: str = Field(..., description="导入类型")
    file_name: str = Field(..., description="文件名")


class ImportJobUpdate(BaseModel):
    id: int = Field(..., description="任务ID")
    status: Optional[str] = Field(None, description="状态")
    success_count: Optional[int] = Field(None, description="成功数量")
    fail_count: Optional[int] = Field(None, description="失败数量")
    error_report: Optional[str] = Field(None, description="错误报告")
