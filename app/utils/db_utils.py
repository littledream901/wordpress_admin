"""数据库工具函数 — MySQL 兼容性适配"""
import logging
import re

from tortoise import connections

_log = logging.getLogger(__name__)


async def safe_count(query) -> int:
    """MySQL 兼容的 count 查询。

    Tortoise ORM 的 .count() 在 MySQL 下从 asyncmy 驱动拿到的是字符串 COUNT 结果，
    内部做 `str - int` 运算触发 TypeError。此函数绕过该 bug，直接用 CAST 转整数。

    Args:
        query: Tortoise QuerySet 实例

    Returns:
        int: 记录总数
    """
    try:
        conn = connections.get("default")
        sql, params = query.query.sql()

        # 截取 FROM 及之后的部分作为子查询
        upper = sql.upper()
        from_idx = upper.index(' FROM ')
        tail = sql[from_idx:]

        # 移除 ORDER BY、LIMIT、OFFSET 子句
        tail = re.sub(r'\s+ORDER\s+BY\s+\S+(\s+(ASC|DESC))?(\s*,\s*\S+(\s+(ASC|DESC))?)*',
                      '', tail, flags=re.IGNORECASE)
        tail = re.sub(r'\s+LIMIT\s+\d+(\s*,\s*\d+)?', '', tail, flags=re.IGNORECASE)
        tail = re.sub(r'\s+OFFSET\s+\d+', '', tail, flags=re.IGNORECASE)

        count_sql = f'SELECT CAST(COUNT(*) AS UNSIGNED) as cnt {tail}'
        result = await conn.execute_query_dict(count_sql, params)
        return int(list(result[0].values())[0])
    except Exception as e:
        _log.warning("safe_count 降级: %s", e)
        # 兜底：只加载 ID 列做计数
        ids = await query.values_list('id', flat=True)
        return len(ids)
