"""1Panel Provider 性能监控 API"""

import asyncio
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Query

from app.models.config_provider import ConfigProvider
from app.schemas.base import Fail, Success
from app.services.onepanel_service import OnePanelAPI

_log = logging.getLogger(__name__)

router = APIRouter(tags=["Monitor"])

# 简单缓存：{provider_id: (timestamp, data)}
_cache: Dict[int, tuple] = {}
_CACHE_TTL = 10  # 缓存 10 秒


async def _query_provider(provider: ConfigProvider, use_cache: bool = True) -> Dict[str, Any]:
    """查询单个 1Panel Provider 的性能数据"""
    if use_cache and provider.id in _cache:
        ts, data = _cache[provider.id]
        if time.time() - ts < _CACHE_TTL:
            return data

    items = {item.config_key: item.config_value for item in
             await provider.items.all() if item.config_value}
    url = str(items.get('url', '') or items.get('OP_URL', '')).strip()
    api_key = str(items.get('api_key', '') or items.get('OP_API_KEY', '') or '')

    if not url or not api_key:
        return {
            "provider_id": provider.id,
            "provider_name": provider.provider_name,
            "status": "offline",
            "error": "缺少 URL 或 API Key 配置",
        }

    if not url.startswith('http'):
        url = 'https://' + url
    base = url.rstrip('/') + '/api/v2'

    ts = str(int(time.time()))
    token = hashlib.md5(f'1panel{api_key}{ts}'.encode('utf-8')).hexdigest()
    headers = {
        '1Panel-Token': token,
        '1Panel-Timestamp': ts,
        'Accept': 'application/json',
    }

    result = {
        "provider_id": provider.id,
        "provider_name": provider.provider_name,
        "url": url,
        "status": "ok",
    }

    try:
        loop = asyncio.get_event_loop()

        # 基础信息 + 实时性能
        def fetch_base():
            return httpx.get(f"{base}/dashboard/base/sda/sda", headers=headers, timeout=30).json()

        base_resp = await loop.run_in_executor(None, fetch_base)
        if base_resp.get('code') == 200:
            data = base_resp['data']
            result["hostname"] = data.get("hostname", "")
            result["os"] = f"{data.get('os', '')} {data.get('platformVersion', '')}"
            result["kernel"] = f"{data.get('kernelVersion', '')} ({data.get('kernelArch', '')})"
            result["cpu_model"] = data.get("cpuModelName", "")
            result["cpu_cores"] = data.get("cpuCores", 0)
            result["cpu_logical"] = data.get("cpuLogicalCores", 0)
            result["virtualization"] = data.get("virtualizationSystem", "")
            result["website_count"] = data.get("websiteNumber", 0)
            result["database_count"] = data.get("databaseNumber", 0)
            result["app_count"] = data.get("appInstalledNumber", 0)

            current = data.get("currentInfo", {})
            result["uptime"] = current.get("timeSinceUptime", "")

            # CPU
            result["cpu_percent"] = current.get("cpuUsedPercent", 0)
            result["cpu_used"] = current.get("cpuUsed", 0)
            result["cpu_total"] = current.get("cpuTotal", 0)

            # Memory
            result["memory_total"] = current.get("memoryTotal", 0)
            result["memory_used"] = current.get("memoryUsed", 0)
            result["memory_free"] = current.get("memoryFree", 0)
            result["memory_available"] = current.get("memoryAvailable", 0)
            result["memory_cache"] = current.get("memoryCache", 0)
            result["memory_percent"] = current.get("memoryUsedPercent", 0)

            # Swap
            result["swap_total"] = current.get("swapMemoryTotal", 0)
            result["swap_used"] = current.get("swapMemoryUsed", 0)
            result["swap_percent"] = current.get("swapMemoryUsedPercent", 0)

            # Load
            result["load1"] = current.get("load1", 0)
            result["load5"] = current.get("load5", 0)
            result["load15"] = current.get("load15", 0)
            result["load_percent"] = current.get("loadUsagePercent", 0)

            # Disk
            disks = current.get("diskData", []) or []
            result["disks"] = [
                {
                    "device": d.get("device", ""),
                    "path": d.get("path", ""),
                    "type": d.get("type", ""),
                    "total": d.get("total", 0),
                    "used": d.get("used", 0),
                    "free": d.get("free", 0),
                    "percent": d.get("usedPercent", 0),
                }
                for d in disks
            ]

            # Network
            result["net_recv"] = current.get("netBytesRecv", 0)
            result["net_sent"] = current.get("netBytesSent", 0)

            # IO
            result["io_read"] = current.get("ioReadBytes", 0)
            result["io_write"] = current.get("ioWriteBytes", 0)

            # Processes
            result["procs"] = current.get("procs", 0)

        else:
            result["status"] = "error"
            result["error"] = base_resp.get('message', f'code={base_resp.get("code")}')

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:200]

    _cache[provider.id] = (time.time(), result)
    return result


@router.get('/onepanel-monitor', summary='查询所有 1Panel Provider 性能指标')
async def get_onepanel_monitor(refresh: bool = Query(default=True, description='是否实时刷新数据')):
    """获取所有 active 的 1Panel Provider 的服务器性能数据

    如果 refresh=true，实时请求各 Provider 的 dashboard API
    如果 refresh=false，仅返回 provider 基本信息
    """
    providers = await ConfigProvider.filter(provider_type="onepanel", status="active").order_by("priority").all()
    if not providers:
        providers = await ConfigProvider.filter(provider_type="onepanel").order_by("priority").all()

    if not providers:
        return Success(data=[])

    if refresh:
        results = []
        for p in providers:
            results.append(await _query_provider(p))
        return Success(data=results)
    else:
        data = [
            {
                "provider_id": p.id,
                "provider_name": p.provider_name,
                "status": "pending",
            }
            for p in providers
        ]
        return Success(data=data)
