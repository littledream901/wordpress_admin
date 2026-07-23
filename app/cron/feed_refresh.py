"""Feed Link 定时刷新：产品导入后周期性拉取 CTX Feed 最新链接。"""
import asyncio
import logging

import httpx

from app.models.site_pipeline import Site
from app.utils.provider_resolver import ProviderResolver

logger = logging.getLogger(__name__)


async def _refresh_site_feed_link(site: Site) -> None:
    """请求 CTX Refresh URL 获取最新 Feed Link 并更新到站点。"""
    if not site.ctx_refresh_url:
        return

    _wp_ssl_val = await ProviderResolver.get_config("onepanel", "wp_verify_ssl", default="true")
    wp_verify_ssl = _wp_ssl_val.lower() != "false"

    async with httpx.AsyncClient(timeout=60, verify=wp_verify_ssl, follow_redirects=True) as client:
        for i in range(1, 7):
            try:
                resp = await client.get(site.ctx_refresh_url)
                if resp.status_code == 200:
                    data = resp.json()
                    links = data.get("feed_links") or []
                    if isinstance(links, list) and links:
                        links = [str(l) for l in links]
                        links = [l for l in links if "/logs/" not in l]
                        if links:
                            site.feed_link = links[0]
                            await site.save()
                            logger.info(
                                "站点 %s Feed Link 已更新: %s",
                                site.domain, links[0],
                            )
                        return
            except Exception as exc:
                logger.warning(
                    "站点 %s CTX Feed 刷新失败，第 %s/6 次: %s",
                    site.domain, i, exc,
                )
            await asyncio.sleep(5)

    logger.warning("站点 %s CTX Feed 刷新最终失败", site.domain)


async def run_feed_refresh_loop():
    """每 30 分钟刷新一次已导入站点的 CTX Feed Link。"""
    # 启动后等待 5 分钟再开始首次刷新，避免与正在进行的导入冲突
    await asyncio.sleep(300)

    while True:
        try:
            sites = await Site.filter(
                ctx_refresh_url__not="",
                woo_import_status__contains="成功",
            ).all()

            if sites:
                logger.info(f"[Feed-Refresh] 开始刷新 {len(sites)} 个站点的 Feed Link")
                for site in sites:
                    try:
                        await _refresh_site_feed_link(site)
                    except Exception:
                        pass
                logger.info("[Feed-Refresh] 本轮刷新完成")
            else:
                logger.debug("[Feed-Refresh] 无需要刷新的站点")
        except Exception:
            pass

        await asyncio.sleep(1800)  # 30 分钟
