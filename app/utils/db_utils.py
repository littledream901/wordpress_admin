"""数据库工具函数 — MySQL 兼容性适配"""
import logging
import re

from tortoise import connections

_log = logging.getLogger(__name__)


async def safe_count(query) -> int:
    """MySQL / SQLite 兼容的 count 查询。

    Tortoise ORM 的 .count() 在 MySQL 下从 asyncmy 驱动拿到的是字符串 COUNT 结果，
    内部做 `str - int` 运算触发 TypeError。此函数绕过该 bug，直接用 CAST 转整数。

    Args:
        query: Tortoise QuerySet 实例

    Returns:
        int: 记录总数
    """
    # 先提取 SQL（只调用一次 .sql()，避免重复调用导致内部状态错误）
    try:
        cache_sql, cache_params = query.query.sql()
    except Exception:
        cache_sql, cache_params = None, None

    try:
        conn = connections.get("default")
        if not cache_sql:
            raise ValueError("query.sql() 返回空")

        # 截取 FROM 及之后的部分作为子查询
        upper = cache_sql.upper()
        from_idx = upper.index(' FROM ')
        tail = _strip_order_by(cache_sql[from_idx:])
        tail = re.sub(r'\s+LIMIT\s+\d+(\s*,\s*\d+)?', '', tail, flags=re.IGNORECASE)
        tail = re.sub(r'\s+OFFSET\s+\d+', '', tail, flags=re.IGNORECASE)

        count_sql = f'SELECT CAST(COUNT(*) AS UNSIGNED) as cnt {tail}'
        result = await conn.execute_query_dict(count_sql, cache_params)
        return int(list(result[0].values())[0])
    except Exception as e:
        _log.warning("safe_count 降级: %s", e)
        # 兜底：用缓存的 SQL 做 COUNT(1)，避免重复调用 query.query.sql()
        if cache_sql:
            try:
                from_idx2 = cache_sql.upper().index(' FROM ')
                sub_tail = _strip_order_by(cache_sql[from_idx2:])
                sub_tail = re.sub(r'\s+LIMIT\s+\d+(\s*,\s*\d+)?', '', sub_tail, flags=re.IGNORECASE)
                sub_tail = re.sub(r'\s+OFFSET\s+\d+', '', sub_tail, flags=re.IGNORECASE)
                count_fallback_sql = f'SELECT COUNT(1) as cnt {sub_tail}'
                result2 = await conn.execute_query_dict(count_fallback_sql, cache_params)
                return int(list(result2[0].values())[0])
            except Exception:
                pass
        # 最终兜底：全量加载 ID 计数
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
