"""数据库工具函数"""
import logging

_log = logging.getLogger(__name__)


async def safe_count(query) -> int:
    """安全计数查询。

    仅使用 Tortoise .count()，失败时返回 0 作为优雅降级。
    不再回退到子查询或全量 ID 加载 —— 那些路径会阻塞事件循环。

    Args:
        query: Tortoise QuerySet 实例

    Returns:
        int: 记录总数（查询失败时返回 0）
    """
    try:
        raw = await query.count()
        return int(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        _log.warning("safe_count 查询失败，返回 0（降级）: %s", exc)
        return 0
