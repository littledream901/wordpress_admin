"""GMC 定时巡检调度

读取 HubStudio Provider 配置：
- gmc_check_cron：cron 表达式，空=禁用（例: */30 * * * *）
- gmc_check_cron_statuses：需要巡检的 GMC 状态列表（JSON），__empty__ 表示从未检测
"""

import asyncio
import json
import logging
import time
from datetime import datetime

from croniter import croniter

_log = logging.getLogger(__name__)

# 默认巡检状态列表（不含 active）
_DEFAULT_STATUSES = ["__empty__", "warning", "suspended", "pending", "unknown",
                     "reviewing", "failed", "query_failed", "Uncreated"]


def _parse_status_filter(raw: str) -> list:
    """解析 gmc_check_cron_statuses 配置，处理 __empty__ 特殊值"""
    try:
        statuses = json.loads(raw) if raw else _DEFAULT_STATUSES
    except (json.JSONDecodeError, TypeError):
        statuses = _DEFAULT_STATUSES
    # 将 __empty__ 替换为空字符串（DB 中从未检测的站点 gmc_status=''）
    return ['' if s == '__empty__' else s for s in statuses if s]


def _calc_sleep_seconds(cron_expr: str) -> float:
    """根据 cron 表达式计算距离下次执行的秒数"""
    now = datetime.now()
    it = croniter(cron_expr, now)
    next_time = it.get_next(datetime)
    delta = (next_time - now).total_seconds()
    return max(delta, 60)  # 最少等 60 秒，避免高频空转


async def _read_cron_config() -> dict:
    """读取 HubStudio 默认 Provider 的 GMC 巡检配置"""
    try:
        from app.models.config_provider import ConfigProvider, ProviderConfigItem
        provider = await ConfigProvider.get_default('hubstudio')
        if not provider:
            return {"cron": "", "statuses": _DEFAULT_STATUSES}
        items = await ProviderConfigItem.get_map(provider.id)
        cron_expr = (items.get('gmc_check_cron', '') or '').strip()
        statuses = _parse_status_filter(items.get('gmc_check_cron_statuses', ''))
        return {"cron": cron_expr, "statuses": statuses}
    except Exception:
        return {"cron": "", "statuses": _DEFAULT_STATUSES}


async def _get_sites_need_gmc_check(statuses: list) -> list:
    """查询需要 GMC 巡检的站点：有 hub_env_id、未删除、GMC 状态在指定列表中"""
    try:
        from app.models.site_pipeline import Site
        sites = await Site.filter(
            hub_env_id__not='',
            is_deleted=False,
            gmc_status__in=statuses,
        ).all()
        return sites
    except Exception as e:
        _log.warning(f"[GMC-Cron] 查询站点失败: {e}")
        return []


async def _dispatch_gmc_check(sites: list) -> int:
    """为站点批量提交 GMC 检查任务（Agent 异步执行）"""
    from app.services.hubstudio_service import HubStudioService
    service = HubStudioService()
    count = 0
    for site in sites:
        try:
            await service.trigger_hub_gmc_check(
                site.id, provider_id=0, execute_now=False,
            )
            count += 1
        except Exception as e:
            _log.warning(f"[GMC-Cron] 站点 {site.domain} 任务提交失败: {e}")
    return count


async def run_gmc_cron_loop():
    """GMC 定时巡检主循环（作为后台任务运行）"""
    _log.info("[GMC-Cron] 启动 GMC 定时巡检调度")

    while True:
        try:
            cfg = await _read_cron_config()
            cron_expr = cfg["cron"]
            statuses = cfg["statuses"]
        except Exception:
            cron_expr = ""
            statuses = _DEFAULT_STATUSES

        if not cron_expr:
            # 未配置 cron，每小时检查一次配置是否启用
            await asyncio.sleep(3600)
            continue

        try:
            sleep_sec = _calc_sleep_seconds(cron_expr)
        except Exception:
            _log.error(f"[GMC-Cron] cron 表达式无效: {cron_expr}")
            await asyncio.sleep(3600)
            continue

        _log.info(f"[GMC-Cron] 下次执行: {datetime.fromtimestamp(time.time() + sleep_sec)}, "
                  f"cron={cron_expr}, 状态={statuses}")
        await asyncio.sleep(sleep_sec)

        # ── 执行巡检 ──
        _log.info(f"[GMC-Cron] 开始巡检，cron={cron_expr}，状态={statuses}")
        try:
            sites = await _get_sites_need_gmc_check(statuses)
            if sites:
                dispatched = await _dispatch_gmc_check(sites)
                _log.info(f"[GMC-Cron] 本轮提交 {dispatched}/{len(sites)} 个站点")
            else:
                _log.info("[GMC-Cron] 无符合条件的站点，跳过")
        except Exception as e:
            _log.error(f"[GMC-Cron] 巡检异常: {e}")
