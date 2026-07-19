"""数据库工具函数"""
import logging
import re

from tortoise import connections

_log = logging.getLogger(__name__)


async def safe_count(query) -> int:
    """MySQL 兼容的 count 查询。

    Tortoise ORM 的 .count() 在 MySQL asyncmy 驱动下可能返回字符串，
    此函数统一转换为 int，并在所有路径失败时回退到全量 ID 计数。

    Args:
        query: Tortoise QuerySet 实例

    Returns:
        int: 记录总数
    """
    # 主路径：直接使用 Tortoise count，兼容 asyncmy 返回字符串的情况
    try:
        raw = await query.count()
        return int(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        _log.debug("safe_count Tortoise .count() 失败，尝试子查询: %s", exc)

    # 路径二：构造 COUNT 子查询
    try:
        cache_sql, cache_params = query.query.sql()
    except Exception:
        cache_sql, cache_params = None, None

    if cache_sql:
        try:
            conn = connections.get("default")
            upper = cache_sql.upper()
            from_idx = upper.index(' FROM ')
            tail = cache_sql[from_idx:]
            tail = _strip_order_by(tail)
            tail = re.sub(r'\s+LIMIT\s+\d+(\s*,\s*\d+)?', '', tail, flags=re.IGNORECASE)
            tail = re.sub(r'\s+OFFSET\s+\d+', '', tail, flags=re.IGNORECASE)
            count_sql = f'SELECT COUNT(1) as cnt {tail}'
            result = await conn.execute_query_dict(count_sql, cache_params)
            return int(list(result[0].values())[0])
        except Exception as exc2:
            _log.debug("safe_count 子查询失败，回退全量 ID: %s", exc2)

    # 路径三：最终兜底 — 全量加载 ID 计数
    ids = await query.values_list('id', flat=True)
    return len(ids)


def _strip_order_by(tail: str) -> str:
    """移除 SQL tail 中的 ORDER BY 子句。

    兼容反引号列名、多列排序、方向关键字。
    """
    # 使用 rfind 截断替代正则，避免贪婪匹配吃掉逗号导致残留
    upper = tail.upper()
    order_pos = upper.rfind(' ORDER BY ')
    if order_pos == -1:
        return tail
    return tail[:order_pos]
