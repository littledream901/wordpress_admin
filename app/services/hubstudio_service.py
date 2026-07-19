"""HubStudio 服务端调度服务

职责：
- 创建/查询 HubStudio 任务
- 按站点派发任务（支持 execute_now 降级直接执行）
- 接收 Agent 回传结果
- Agent 心跳检测
- 写回 Site 表

不负责：
- 启动本地 Connector
- 执行本地 HubStudio API 调用
- 浏览器控制
（这些由 Agent / execute_now 降级负责）
"""

import json
import os
import socket
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.controllers.gmail_account import gmail_account_controller
from app.core.exceptions import HubStudioError, SiteNotFoundError
from app.log import logger
from app.models.config_provider import ConfigProvider, ProviderConfigItem, ResourceProviderBinding
from app.models.operation_job import OperationJob
from app.models.site_pipeline import HubStudioAgentHeartbeat, HubStudioJob, Site
from app.utils.config_reader import get_provider_info


# 任务类型定义
JOB_TYPES = ["create_env", "create_account", "update_env", "wp_login", "gmc_check", "open_env"]

# Agent 心跳超时阈值（秒）
AGENT_HEARTBEAT_TIMEOUT = int(os.getenv("HUB_AGENT_HEARTBEAT_TIMEOUT", "120"))


class HubStudioOrchestrationService:
    """HubStudio 任务编排服务（服务端）"""

    # ── 任务管理 ──

    async def create_job(
        self,
        site_id: int,
        domain: str,
        job_type: str = "create_env",
        payload: dict = None,
        provider_id: int = 0,
    ) -> HubStudioJob:
        """创建 HubStudio 任务"""
        if job_type not in JOB_TYPES:
            raise ValueError(f"不支持的任务类型: {job_type}，有效值: {JOB_TYPES}")

        if not provider_id:
            provider_id = await self._resolve_provider_id(site_id)

        job = await HubStudioJob.create(
            site_id=site_id,
            domain=domain,
            provider_id=provider_id,
            job_type=job_type,
            status="pending",
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
        )

        await OperationJob.create(
            resource_type="site",
            resource_id=site_id,
            domain=domain,
            action_type=f"hub_{job_type}",
            status="running",
            payload_json=job.payload_json,
            started_at=datetime.now(),
        )

        logger.info(f"HubStudio 任务已创建: id={job.id}, type={job_type}, domain={domain}, provider={provider_id}")
        return job

    async def dispatch_for_site(
        self,
        site_id: int,
        job_type: str = "create_env",
        payload: dict = None,
        provider_id: int = 0,
        execute_now: bool = False,
        agent_worker: str = "",
    ) -> Tuple[HubStudioJob, Optional[dict]]:
        """按站点派发任务

        Args:
            execute_now: True=后端直接同步执行（Agent 不在时降级）
            agent_worker: execute_now 模式下标记执行者

        Returns:
            (job, execute_result) - execute_result 仅在 execute_now=True 时有值
        """
        site = await Site.filter(id=site_id).first()
        if not site:
            raise SiteNotFoundError(site_id=site_id)

        if payload is None:
            payload = self._build_default_payload(site, job_type)

        if not provider_id:
            provider_id = await self._resolve_provider_id(site_id)

        # update_env / create_account / wp_login / gmc_check / open_env 必须有 hub_env_id
        if job_type in ("update_env", "create_account", "wp_login", "gmc_check", "open_env") and not site.hub_env_id:
            raise ValueError(f"站点 {site.domain} 尚未创建环境（hub_env_id 为空），请先执行 create_env")

        # create_env / update_env: 从 Gmail 构建备注字段写入 payload
        if job_type in ("create_env", "update_env"):
            payload = await self._enrich_remark_from_gmail(payload, site)

        # update_env: 从 provider 配置中读取代理配置，写入 payload
        if job_type == "update_env":
            payload = await self._enrich_update_env_payload(payload, provider_id)

        # create_account: 自动分配 Gmail 并将凭证写入 payload
        if job_type == "create_account":
            payload = await self._enrich_create_account_payload(payload, site)

        # wp_login: 注入 Gmail + WordPress 凭证，供 executor 自动登录
        if job_type == "wp_login":
            payload = await self._enrich_wp_login_payload(payload, site)

        job = await self.create_job(
            site_id=site.id,
            domain=site.domain,
            job_type=job_type,
            payload=payload,
            provider_id=provider_id,
        )

        if execute_now:
            result = await self._execute_job_sync(job, agent_worker or "server-fallback")
            return job, result

        return job, None

    async def _execute_job_sync(self, job: HubStudioJob, worker_name: str) -> dict:
        """后端直接同步执行任务（Agent 离线降级）

        仅在以下条件满足时可用：
        1. 后端与 HubStudio Connector 运行在同一台 Windows 机器上
        2. Connector 端口可达
        """
        job.status = "running"
        job.worker_name = worker_name
        job.started_at = datetime.now()
        await job.save()

        try:
            from app.services.hubstudio_executor import create_executor_from_config

            # 从 provider 配置构建 runtime + executor（含代理配置）
            provider_config = await self._get_provider_config(job.provider_id)
            runtime, executor = create_executor_from_config(provider_config)

            # 检查 Connector 是否可达
            if not runtime.is_port_open():
                raise HubStudioError("connector", detail=f"端口 {runtime.http_port} 不可达")

            job_dict = {
                "id": job.id,
                "job_type": job.job_type,
                "domain": job.domain,
                "site_id": job.site_id,
                "payload": json.loads(job.payload_json or "{}"),
            }
            result = executor.execute(job_dict)
            ok = result.get("status") == "success"
            await self.report_job_result(
                job.id,
                "success" if ok else "failed",
                json.dumps(result, ensure_ascii=False),
                result.get("error", ""),
                worker_name,
            )
            return result
        except ImportError:
            return {"status": "failed", "error": "hubstudio_executor 模块不可用，请安装依赖"}
        except Exception as e:
            err_msg = str(e)
            await self.report_job_result(job.id, "failed", "{}", err_msg, worker_name)
            return {"status": "failed", "error": err_msg}

    async def _get_provider_config(self, provider_id: int) -> dict:
        """从配置中心读取 provider 配置"""
        config = {
            "connector_dir": r"D:\Program Files\Hubstudio",
            "exe_name": "hubstudio_connector.exe",
            "http_port": "6873",
            "base_url": "http://localhost:6873",
            "app_id": "",
            "app_secret": "",
            "group_code": "",
            "real_kernel_version": "137",
            # 代理相关字段（参考 hubstudio_s3_update_env.py FIXED_PROXY_CONFIG）
            "use_fixed_proxy": "true",
            "proxy_type_name": "HTTP",
            "proxy_host": "server.iphtml.biz",
            "proxy_port": "15000",
            "proxy_account": "uid-27498-zone-hubstudio",
            "proxy_password": "",
            "proxy_country_code": "US",
            "proxy_city": "New York",
            "proxy_province": "CA",
            "as_dynamic_type": "1",
            "ip_get_rule_type": "1",
        }
        if provider_id:
            db_items = await ProviderConfigItem.get_map(provider_id)
            for key in config:
                if key in db_items:
                    config[key] = db_items[key]
        # 环境变量覆盖
        env_map = {
            "connector_dir": "HUB_CONNECTOR_DIR",
            "exe_name": "HUB_EXE_NAME",
            "http_port": "HUB_HTTP_PORT",
            "base_url": "HUB_BASE_URL",
            "app_id": "HUB_APP_ID",
            "app_secret": "HUB_APP_SECRET",
            "group_code": "HUB_GROUP_CODE",
            "real_kernel_version": "HUB_KERNEL_VER",
            "use_fixed_proxy": "HUB_USE_FIXED_PROXY",
            "proxy_type_name": "HUB_PROXY_TYPE",
            "proxy_host": "HUB_PROXY_HOST",
            "proxy_port": "HUB_PROXY_PORT",
            "proxy_account": "HUB_PROXY_ACCOUNT",
            "proxy_password": "HUB_PROXY_PASSWORD",
            "proxy_country_code": "HUB_PROXY_COUNTRY_CODE",
            "proxy_city": "HUB_PROXY_CITY",
            "proxy_province": "HUB_PROXY_PROVINCE",
            "as_dynamic_type": "HUB_PROXY_AS_DYNAMIC_TYPE",
        }
        for key, env in env_map.items():
            if os.getenv(env):
                config[key] = os.getenv(env)
        return config

    async def list_jobs(
        self,
        page: int = 1,
        page_size: int = 20,
        domain: str = "",
        status: str = "",
        job_type: str = "",
        provider_id: int = None,
    ) -> tuple:
        """查询任务列表"""
        from tortoise.expressions import Q

        q = Q()
        if domain:
            q &= Q(domain__contains=domain)
        if status:
            q &= Q(status=status)
        if job_type:
            q &= Q(job_type=job_type)
        if provider_id is not None:
            q &= Q(provider_id=provider_id)

        total = await HubStudioJob.filter(q).count()
        objs = await HubStudioJob.filter(q).order_by("-id").offset((page - 1) * page_size).limit(page_size)
        data = [await obj.to_dict() for obj in objs]
        return total, data

    async def get_job(self, job_id: int) -> Optional[HubStudioJob]:
        """获取任务详情"""
        return await HubStudioJob.filter(id=job_id).first()

    async def retry_job(self, job_id: int, execute_now: bool = False) -> Optional[HubStudioJob]:
        """重试失败任务，同步重置关联的 OperationJob"""
        job = await HubStudioJob.filter(id=job_id).first()
        if not job:
            return None
        job.status = "pending"
        job.error_message = ""
        job.retry_count = (job.retry_count or 0) + 1
        job.started_at = None
        job.finished_at = None
        await job.save()

        # 同步重置关联的 OperationJob 状态
        op_job = await OperationJob.filter(
            resource_type="site", resource_id=job.site_id,
            action_type=f"hub_{job.job_type}",
            status__in=["running", "failed"],
        ).order_by("-id").first()
        if op_job:
            op_job.status = "pending"
            op_job.error_message = ""
            op_job.finished_at = None
            await op_job.save()
            logger.info(f"HubStudio 重试同步 OperationJob: id={op_job.id}")

        logger.info(f"HubStudio 任务已重试: id={job.id}, retry={job.retry_count}")

        if execute_now:
            # 重试同时立即执行
            result = await self._execute_job_sync(job, "server-fallback")
            return job, result

        return job

    async def cancel_job(self, job_id: int) -> Optional[HubStudioJob]:
        """取消任务（仅 pending/running 状态可取消）"""
        job = await HubStudioJob.filter(id=job_id).first()
        if not job:
            return None
        if job.status not in ("pending", "running"):
            raise ValueError(f"任务状态为 {job.status}，不可取消")
        job.status = "cancelled"
        job.finished_at = datetime.now()
        await job.save()
        logger.info(f"HubStudio 任务已取消: id={job.id}, type={job.job_type}, domain={job.domain}")
        return job

    async def batch_cancel_jobs(self, job_ids: list[int]) -> dict:
        """批量取消任务"""
        success, fail = 0, 0
        results = []
        for jid in job_ids:
            try:
                await self.cancel_job(jid)
                results.append({"job_id": jid, "ok": True})
                success += 1
            except Exception as e:
                results.append({"job_id": jid, "ok": False, "error": str(e)})
                fail += 1
        logger.info(f"HubStudio 批量取消: success={success}, fail={fail}")
        return {"success": success, "fail": fail, "total": len(job_ids), "results": results}

    # ── Agent 心跳 ──

    async def agent_heartbeat(self, worker_name: str, provider_id: int = 0,
                              task_id: int = 0, task_status: str = "") -> dict:
        """Agent 上报心跳"""
        heartbeat, created = await HubStudioAgentHeartbeat.get_or_create(
            worker_name=worker_name,
            defaults={
                "provider_id": provider_id,
                "status": "online",
                "last_heartbeat": datetime.now(),
                "total_tasks": 0,
            }
        )
        if not created:
            heartbeat.last_heartbeat = datetime.now()
            heartbeat.status = "online"
            heartbeat.provider_id = provider_id or heartbeat.provider_id
        if task_id:
            heartbeat.last_task_id = task_id
            heartbeat.last_task_status = task_status
            heartbeat.total_tasks = (heartbeat.total_tasks or 0) + 1
        await heartbeat.save()
        return {"ok": True, "worker_name": worker_name, "online": True}

    async def get_agents_status(self) -> List[dict]:
        """查询所有 Agent 的在线状态"""
        agents = await HubStudioAgentHeartbeat.all()
        result = []
        threshold = datetime.now() - timedelta(seconds=AGENT_HEARTBEAT_TIMEOUT)
        for agent in agents:
            # last_heartbeat 是 timezone-aware datetime，统一转成 naive 再比较
            last_hb = agent.last_heartbeat
            if last_hb and hasattr(last_hb, 'tzinfo') and last_hb.tzinfo is not None:
                last_hb = last_hb.replace(tzinfo=None)
            is_online = last_hb and last_hb > threshold
            result.append({
                "worker_name": agent.worker_name,
                "provider_id": agent.provider_id,
                "online": is_online,
                "last_heartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
                "total_tasks": agent.total_tasks,
                "last_task_id": agent.last_task_id,
                "last_task_status": agent.last_task_status,
            })
        return result

    async def is_any_agent_online(self) -> bool:
        """检查是否有 Agent 在线"""
        agents = await self.get_agents_status()
        return any(a["online"] for a in agents)

    # ── Agent 配置拉取 ──

    async def get_agent_config(self, provider_id: int) -> dict:
        """Agent 启动后拉取 Provider 配置（以 DB 为主，环境变量兜底）。

        provider_id=0 时自动解析默认 hubstudio Provider。
        返回的 key 名与 Agent 端 _load_config() 一致，可直接 merge。
        额外返回 _resolved_provider_id 告知 Agent 解析后的实际 ID。
        """
        config = {}
        resolved_id = provider_id

        # provider_id=0：解析默认 hubstudio Provider
        if not provider_id:
            # 诊断：先查所有 hubstudio 类型的 provider
            all_hub = await ConfigProvider.filter(provider_type="hubstudio").all()
            if not all_hub:
                logger.warning("Agent 请求默认 Provider，但系统中没有任何 hubstudio 类型的 Provider")
            else:
                active_list = [p for p in all_hub if p.status == "active"]
                default_list = [p for p in active_list if p.is_default]
                logger.info(
                    f"hubstudio Provider 统计: 总数={len(all_hub)}, "
                    f"active={len(active_list)}, is_default={len(default_list)}"
                )
                if not active_list:
                    logger.warning(
                        f"存在 {len(all_hub)} 个 hubstudio Provider，但全部为非 active 状态: "
                        f"{', '.join(f'{p.provider_name}({p.status})' for p in all_hub)}"
                    )
                elif not default_list:
                    logger.warning(
                        f"存在 {len(active_list)} 个 active hubstudio Provider，但未设置默认: "
                        f"{', '.join(p.provider_name for p in active_list)}"
                    )

            default = await ConfigProvider.get_default("hubstudio")
            if default:
                provider_id = default.id
                resolved_id = default.id
                logger.info(f"Agent 请求默认 Provider → 解析为 provider_id={resolved_id} ({default.provider_name})")
            else:
                logger.warning("Agent 请求默认 Provider，但系统中无符合条件的 hubstudio Provider（需 status=active 且 is_default=True，或至少有一个 active）")

        # 1. 从 DB 读取 provider 配置
        if provider_id:
            db_items = await ProviderConfigItem.get_map(provider_id)
            # DB key 映射到 Agent 期望的 key 名
            _key_map = {
                "app_id": "app_id",
                "app_secret": "app_secret",
                "group_code": "group_code",
                "kernel_version": "real_kernel_version",
                "real_kernel_version": "real_kernel_version",
                "proxy_type_name": "default_proxy_type_name",
                "ui_language": "default_ui_language",
                "admin_site_name": "admin_site_name",
                "admin_site_alias": "admin_site_alias",
                "admin_account_name": "admin_account_name",
                "admin_account_password": "admin_account_password",
            }
            for db_key, agent_key in _key_map.items():
                if db_key in db_items:
                    config[agent_key] = db_items[db_key]

        # 2. 环境变量兜底（仅 provider_id=0 且无默认 Provider 时生效）
        if not resolved_id:
            _env_fallbacks = {
                "app_id": "HUB_APP_ID",
                "app_secret": "HUB_APP_SECRET",
                "group_code": "HUB_GROUP_CODE",
                "real_kernel_version": "HUB_KERNEL_VER",
            }
            for key, env_var in _env_fallbacks.items():
                if key not in config or not config[key]:
                    val = os.getenv(env_var, "")
                    if val:
                        config[key] = val

        config["_resolved_provider_id"] = resolved_id
        return config

    # ── Agent 领取/回传 ──

    async def claim_next_pending_job(self, worker_name: str, provider_id: int = None) -> Optional[HubStudioJob]:
        """Agent 领取下一个待执行任务"""
        q = HubStudioJob.filter(status="pending")
        if provider_id:
            q = q.filter(provider_id=provider_id)
        job = await q.order_by("id").first()
        if not job:
            return None
        job.status = "running"
        job.worker_name = worker_name
        job.started_at = datetime.now()

        # 刷新 payload：create_account/update_env/wp_login/gmc_check 依赖 hub_env_id，
        # 任务创建时 hub_env_id 可能为空（先于 create_env 完成），此时从 site 重新获取
        if job.job_type in ("create_account", "update_env", "wp_login", "gmc_check"):
            site = await Site.filter(id=job.site_id).first()
            if site and site.hub_env_id:
                try:
                    payload = json.loads(job.payload_json or "{}")
                    need_save = False
                    if not payload.get("hub_env_id"):
                        payload["hub_env_id"] = site.hub_env_id
                        need_save = True
                        logger.info(f"任务 [{job.id}] payload.hub_env_id 已刷新: {site.hub_env_id}")
                    # create_account: 也刷新 Gmail 凭证（任务可能在 _enrich_create_account_payload 之前创建）
                    if job.job_type == "create_account":
                        from app.models.gmail_account import GmailAccount
                        if not payload.get("gmail_username"):
                            gmail = await GmailAccount.filter(assigned_site_id=job.site_id).first()
                            if not gmail:
                                gmail, _ = await gmail_account_controller.auto_assign_to_site(job.site_id)
                            if gmail and gmail.username and gmail.password:
                                payload["gmail_username"] = gmail.username
                                payload["gmail_password"] = gmail.password
                                payload["gmail_2fa_key"] = gmail.two_fa_key or ""
                                need_save = True
                                logger.info(f"任务 [{job.id}] Gmail 凭证已刷新: {gmail.username}")
                    if need_save:
                        job.payload_json = json.dumps(payload, ensure_ascii=False)
                except Exception:
                    pass

        await job.save()

        # 心跳更新
        await self.agent_heartbeat(worker_name, provider_id=job.provider_id or 0,
                                   task_id=job.id, task_status="running")
        logger.info(f"Agent [{worker_name}] 领取任务: id={job.id}, type={job.job_type}, domain={job.domain}")
        return job

    async def report_job_result(
        self,
        job_id: int,
        status: str,
        result_json: str = "{}",
        error_message: str = "",
        worker_name: str = "",
    ) -> Optional[HubStudioJob]:
        """Agent 回传任务结果（同时更新 Site 和 OperationJob）"""
        job = await HubStudioJob.filter(id=job_id).first()
        if not job:
            return None

        job.status = status
        job.result_json = result_json
        job.error_message = error_message
        if worker_name:
            job.worker_name = worker_name
        job.finished_at = datetime.now()
        await job.save()

        # 心跳更新
        if worker_name:
            await self.agent_heartbeat(worker_name, task_id=job.id, task_status=status)

        await self._sync_site_from_job(job, status, result_json, error_message)
        await self._sync_operation_job(job, status, result_json, error_message)

        logger.info(
            f"HubStudio 任务已完成: id={job.id}, status={status}, "
            f"worker={job.worker_name}, error={error_message[:100] if error_message else 'none'}"
        )
        return job

    # ── Site 操作快捷入口 ──

    async def trigger_hub_env(self, site_id: int, provider_id: int = 0,
                               execute_now: bool = False) -> Tuple[HubStudioJob, Optional[dict]]:
        return await self.dispatch_for_site(site_id, "create_env", provider_id=provider_id, execute_now=execute_now)

    async def trigger_hub_account(self, site_id: int, provider_id: int = 0,
                                   execute_now: bool = False) -> Tuple[HubStudioJob, Optional[dict]]:
        return await self.dispatch_for_site(site_id, "create_account", provider_id=provider_id, execute_now=execute_now)

    async def trigger_hub_update(self, site_id: int, provider_id: int = 0,
                                  execute_now: bool = False) -> Tuple[HubStudioJob, Optional[dict]]:
        return await self.dispatch_for_site(site_id, "update_env", provider_id=provider_id, execute_now=execute_now)

    async def trigger_hub_control(self, site_id: int, provider_id: int = 0,
                                   execute_now: bool = False) -> Tuple[HubStudioJob, Optional[dict]]:
        return await self.dispatch_for_site(site_id, "wp_login", provider_id=provider_id, execute_now=execute_now)

    async def trigger_hub_gmc_check(self, site_id: int, provider_id: int = 0,
                                     execute_now: bool = False) -> Tuple[HubStudioJob, Optional[dict]]:
        return await self.dispatch_for_site(site_id, "gmc_check", provider_id=provider_id, execute_now=execute_now)

    async def trigger_hub_open_env(self, site_id: int, provider_id: int = 0,
                                    execute_now: bool = False) -> Tuple[HubStudioJob, Optional[dict]]:
        """通过 Agent 打开 HubStudio 浏览器环境

        只派发任务不执行同步（打开浏览器讲究时效，避免服务端直连 Connector）。
        Agent 离线时直接拒绝，不滞留待执行任务。
        """
        if not execute_now and not await self.is_any_agent_online():
            raise ValueError("没有在线的 HubStudio Agent，无法打开浏览器环境")

        site = await Site.filter(id=site_id).first()
        if not site:
            raise SiteNotFoundError(site_id=site_id)
        if not site.hub_env_id:
            raise ValueError(f"站点 {site.domain} 尚未创建环境（hub_env_id 为空），请先执行创建环境")

        logger.info(f"[open_env] 派发任务: site_id={site_id}, domain={site.domain}, "
                    f"env_id={site.hub_env_id}, provider_id={provider_id}")
        return await self.dispatch_for_site(site_id, "open_env", provider_id=provider_id, execute_now=execute_now)

    # ── 内部辅助 ──

    async def _enrich_update_env_payload(self, payload: dict, provider_id: int) -> dict:
        """为 update_env 任务从 provider 配置中补充代理配置

        将 provider 中存储的代理字段写入 payload.proxy_config，
        确保 Agent 领取任务时也能获得代理配置。
        """
        if not provider_id or payload.get("proxy_config"):
            return payload  # 已有代理配置或无效 provider，不覆盖

        try:
            provider_config = await self._get_provider_config(provider_id)
        except Exception:
            return payload

        proxy_config = {}
        field_map = {
            "proxyTypeName": "proxy_type_name",
            "asDynamicType": "as_dynamic_type",
            "proxyHost": "proxy_host",
            "proxyPort": "proxy_port",
            "proxyAccount": "proxy_account",
            "proxyPassword": "proxy_password",
            "referenceCountryCode": "proxy_country_code",
            "referenceCity": "proxy_city",
            "referenceProvince": "proxy_province",
            "ipGetRuleType": "ip_get_rule_type",
        }
        for api_key, config_key in field_map.items():
            val = provider_config.get(config_key)
            if val is not None and str(val).strip() != "":
                try:
                    proxy_config[api_key] = int(val) if isinstance(val, int) or val.isdigit() else str(val).strip()
                except Exception:
                    proxy_config[api_key] = str(val).strip()

        if proxy_config:
            payload["proxy_config"] = proxy_config
            logger.info(f"[update_env] 已从 provider[{provider_id}] 加载代理配置: "
                        f"type={proxy_config.get('proxyTypeName')}, "
                        f"host={proxy_config.get('proxyHost')}")

        return payload

    async def _enrich_remark_from_gmail(self, payload: dict, site: Site) -> dict:
        """从已分配的 Gmail 中提取地址/邮箱信息，写入 remark_fields

        供 create_env / update_env 使用，按 REMARK_FIELD_MAP 顺序拼接备注：
        ShippingAddress_1 → City → Province/State → Zip_code → Country → Recovery_Email
        """
        if payload.get("remark_fields"):
            return payload  # 已有备注字段，不覆盖

        from app.models.gmail_account import GmailAccount

        gmail = await GmailAccount.filter(assigned_site_id=site.id).first()
        if not gmail:
            logger.info(f"[remark] 站点无 Gmail，跳过备注构建")
            return payload

        remark_fields = {}
        field_map = {
            "ShippingAddress_1": getattr(gmail, "shipping_address_1", "") or "",
            "City": getattr(gmail, "city", "") or "",
            "Province/State": getattr(gmail, "province_state", "") or "",
            "Zip_code": getattr(gmail, "zip_code", "") or "",
            "Country": getattr(gmail, "country", "") or "",
            "Recovery_Email": getattr(gmail, "recovery_email", "") or "",
        }
        for key, val in field_map.items():
            v = str(val).strip() if val else ""
            if v:
                remark_fields[key] = v

        if remark_fields:
            payload["remark_fields"] = remark_fields
            logger.info(f"[remark] 已从 Gmail 构建备注字段: {list(remark_fields.keys())}")
        else:
            logger.info(f"[remark] Gmail 无地址/邮箱字段，备注为空")

        return payload

    # 旧方法名保留别名
    _enrich_update_env_remark = _enrich_remark_from_gmail

    async def _enrich_create_account_payload(self, payload: dict, site: Site) -> dict:
        """为 create_account 任务自动分配 Gmail 并写入凭证 + 备注字段

        确保 Agent/executor 能拿到 Gmail 账号密码，在 HubStudio 中创建 Gmail 平台账号，
        并在创建账号后写备注（地址/邮箱）。
        """
        if payload.get("gmail_username") and payload.get("gmail_password"):
            return payload  # 已有 Gmail 凭证，不覆盖

        from app.models.gmail_account import GmailAccount

        # 先查站点已有分配的 Gmail
        gmail = await GmailAccount.filter(assigned_site_id=site.id).first()
        if not gmail:
            # 自动分配
            gmail, _ = await gmail_account_controller.auto_assign_to_site(site.id)

        if gmail and gmail.username and gmail.password:
            payload["gmail_username"] = gmail.username
            payload["gmail_password"] = gmail.password
            payload["gmail_2fa_key"] = gmail.two_fa_key or ""
            logger.info(f"[create_account] Gmail 凭证已注入: {gmail.username}")

            # 同时写入备注字段，供 executor 创建账号后更新环境备注
            if not payload.get("remark_fields"):
                remark_fields = {}
                field_map = {
                    "ShippingAddress_1": getattr(gmail, "shipping_address_1", "") or "",
                    "City": getattr(gmail, "city", "") or "",
                    "Province/State": getattr(gmail, "province_state", "") or "",
                    "Zip_code": getattr(gmail, "zip_code", "") or "",
                    "Country": getattr(gmail, "country", "") or "",
                    "Recovery_Email": getattr(gmail, "recovery_email", "") or "",
                }
                for key, val in field_map.items():
                    v = str(val).strip() if val else ""
                    if v:
                        remark_fields[key] = v
                if remark_fields:
                    payload["remark_fields"] = remark_fields
        else:
            logger.warning(f"[create_account] 无可用 Gmail 凭证，将只创建 WordPress 后台账号")

        return payload

    async def _enrich_wp_login_payload(self, payload: dict, site: Site) -> dict:
        """为 wp_login 任务注入 WordPress 登录凭证

        executor 使用这些凭证自动登录对应网站。
        """
        # WordPress 后台凭证（来自 executor 默认配置，这里做显式传递）
        if not payload.get("wp_username"):
            payload["wp_username"] = "admin"
        if not payload.get("wp_password"):
            payload["wp_password"] = ""

        return payload

    async def _resolve_provider_id(self, site_id: int) -> int:
        binding = await ResourceProviderBinding.filter(
            resource_type="site", resource_id=site_id, provider_type="hubstudio"
        ).first()
        if binding:
            return binding.provider_id
        default = await ConfigProvider.get_default("hubstudio")
        return default.id if default else 0

    def _build_default_payload(self, site: Site, job_type: str) -> dict:
        """构建默认任务 payload

        调用方可通过 dispatch_for_site(payload={...}) 覆盖任意字段。
        代理配置通过 payload.proxy_config 或 payload.proxy_type_name 等字段传入。
        """
        base = {
            "site_id": site.id,
            "domain": site.domain,
            "login_url": site.login_url,
            "server_ip": site.server_ip,
        }
        if job_type == "create_env":
            return {**base, "hub_env_id": site.hub_env_id}
        elif job_type == "create_account":
            return {**base, "hub_env_id": site.hub_env_id}
        elif job_type == "update_env":
            # update_env 支持额外字段:
            #   remark_fields: dict  (Address/City/State/Zip/Country/Email)
            #   proxy_config: dict   (完整代理配置)
            #   proxy_type_name: str (HTTP/SOCKS5/不使用代理)
            #   proxy_host/port/account/password/country_code/city/province: str
            return {
                **base,
                "hub_env_id": site.hub_env_id,
            }
        elif job_type == "wp_login":
            return {**base, "hub_env_id": site.hub_env_id, "login_url": site.login_url, "feed_link": site.feed_link}
        elif job_type == "gmc_check":
            return {**base, "hub_env_id": site.hub_env_id}
        elif job_type == "open_env":
            return {**base, "hub_env_id": site.hub_env_id}
        return base

    async def _sync_site_from_job(self, job: HubStudioJob, status: str, result_json: str, error_message: str):
        site = await Site.filter(id=job.site_id).first()
        if not site:
            return

        site.hub_status = f"{job.job_type}:{status}"
        site.hub_last_action = job.job_type
        site.pipeline_status = f"hubstudio:{status}"

        site.append_log({
            "source": "hubstudio",
            "job_id": job.id,
            "job_type": job.job_type,
            "status": status,
            "worker_name": job.worker_name,
            "error_message": error_message,
            "result_json": result_json,
            "provider": get_provider_info("hubstudio"),
        })

        if status == "success":
            try:
                result = json.loads(result_json or "{}")
                if job.job_type == "create_env":
                    env_id = result.get("env_id") or result.get("containerCode") or result.get("id") or result.get("code")
                    if env_id:
                        site.hub_env_id = str(env_id)
                    env_name = result.get("containerName")
                    if env_name:
                        site.hub_env_name = str(env_name)
                elif job.job_type == "create_account":
                    account_id = result.get("account_id") or result.get("accountId")
                    if account_id:
                        site.hub_account_id = str(account_id)
                    # 自动分配 Gmail 账号（仅当站点尚未分配 Gmail 时）
                    existing_gmail = await gmail_account_controller.model.filter(
                        assigned_site_id=job.site_id
                    ).first()
                    if existing_gmail:
                        logger.info(f"[create_account] 站点已有 Gmail ({existing_gmail.username})，跳过分配")
                    else:
                        gmail, _ = await gmail_account_controller.auto_assign_to_site(job.site_id)
                        if gmail:
                            logger.info(f"[create_account] Gmail 已自动分配: {gmail.username} -> site={job.site_id}")
                        else:
                            logger.warning(f"[create_account] 无可用的 Gmail 账号分配给 site={job.site_id}")
                elif job.job_type == "wp_login":
                    gmc_status = result.get("gmc_status", "")
                    if gmc_status:
                        site.gmc_status = gmc_status
                    gmc_data = result.get("gmc_data")
                    if gmc_data:
                        site.gmc_data = json.dumps(gmc_data, ensure_ascii=False)
                    logger.info(f"[wp_login] GMC 数据已回写: gmc_status={gmc_status}")
                elif job.job_type == "gmc_check":
                    gmc_status = result.get("gmc_status", "")
                    if gmc_status:
                        site.gmc_status = gmc_status
                    gmc_data = result.get("gmc_data")
                    if gmc_data:
                        site.gmc_data = json.dumps(gmc_data, ensure_ascii=False)
                    logger.info(f"[gmc_check] GMC 数据已回写: gmc_status={gmc_status}")
            except Exception:
                pass

        await site.save()

    async def _sync_operation_job(self, job: HubStudioJob, status: str, result_json: str, error_message: str):
        op_job = await OperationJob.filter(
            resource_type="site", resource_id=job.site_id,
            action_type=f"hub_{job.job_type}", status="running"
        ).order_by("-id").first()
        if not op_job:
            return

        ok = status == "success"
        op_job.status = "success" if ok else "failed"
        if ok:
            try:
                result = json.loads(result_json or "{}")
            except Exception:
                result = {"raw": result_json}
            result["provider"] = get_provider_info("hubstudio")
            op_job.result_json = json.dumps(result, ensure_ascii=False)
        if error_message:
            op_job.error_message = error_message
        op_job.finished_at = datetime.now()
        await op_job.save()


HubStudioService = HubStudioOrchestrationService
