"""
Task 执行器包 —— 独立的业务任务执行引擎。

当前包含：
  - runner.py      TaskRunner 基类（生命周期、_exec、_complete_job）
  - provision.py   ProvisionTaskRunner（1Panel 建站 10 步全流程）

设计原则：
  - 执行器与 API 层解耦，可直接导入使用
  - 所有任务通过 OperationJob 统一追踪
  - 线程池执行同步服务调用，不阻塞事件循环
"""

from .runner import TaskRunner, task_runner
from .provision import ProvisionTaskRunner, provision_task_runner

__all__ = [
    "TaskRunner", "task_runner",
    "ProvisionTaskRunner", "provision_task_runner",
]
