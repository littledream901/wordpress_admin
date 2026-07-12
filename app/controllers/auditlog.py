"""审计日志控制器 —— 查询专用（不对外暴露 CUD）"""
from app.core.crud import CRUDBase
from app.models.admin import AuditLog
from app.schemas.auditlog import AuditLogCreate, AuditLogUpdate


class AuditLogController(CRUDBase[AuditLog, AuditLogCreate, AuditLogUpdate]):
    def __init__(self):
        super().__init__(model=AuditLog)


auditlog_controller = AuditLogController()
