"""Feed 文件定时清理：每小时删除过期的已替换文件。

过期策略（优先级）：
  1. 文件的 expires_at 字段（由创建时设定）
  2. Provider 配置: woo.feed_expire_days
  3. 环境变量: FEED_EXPIRE_DAYS
  4. 默认值: 3 天
"""
import os
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_FALLBACK_EXPIRE_DAYS = 3


async def _get_expire_days() -> int:
    """从 Provider / 环境变量获取 Feed 过期天数。"""
    try:
        from app.utils.provider_resolver import ProviderResolver
        val = await ProviderResolver.get_config("woo", "feed_expire_days", default=None)
        if val is not None:
            days = int(val)
            if days > 0:
                return days
    except Exception:
        pass
    try:
        from app.settings import settings
        return int(settings.FEED_EXPIRE_DAYS)
    except Exception:
        return _FALLBACK_EXPIRE_DAYS


async def run_feed_cleanup_loop():
    """每小时清理一次状态为 replaced 且已过期的 Feed 文件。"""
    # 启动时先等一轮，确保 ORM 已就绪
    await asyncio.sleep(60)

    while True:
        try:
            from app.models.feed_file import FeedFile

            expire_days = await _get_expire_days()
            cutoff = datetime.now()
            legacy_cutoff = cutoff - timedelta(days=expire_days)

            # 1. 已明确过期的（有 expires_at 且已过期）
            expired = await FeedFile.filter(
                status="replaced",
                expires_at__isnull=False,
                expires_at__lt=cutoff,
            ).all()

            # 2. 无 expires_at 但创建时间已超期的旧文件
            legacy = await FeedFile.filter(
                status="replaced",
                expires_at__isnull=True,
                created_at__lt=legacy_cutoff,
            ).all()

            all_expired = list(expired) + list(legacy)
            for feed in all_expired:
                for fpath in (feed.processed_file,):
                    if fpath and os.path.exists(fpath):
                        os.remove(fpath)
                await feed.delete()

            if all_expired:
                logger.info(
                    "[Feed] 定时清理: 已删除 %d 个过期文件 (有expires_at: %d, 旧文件: %d, 策略=%d天)",
                    len(all_expired), len(expired), len(legacy), expire_days,
                )
        except Exception:
            pass

        await asyncio.sleep(3600)
