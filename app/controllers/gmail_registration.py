"""Gmail 注册流程 Controller

职责：
- CRUD：create / update / list / delete
- 流程编排：创建转发 → 创建环境 → 获取号码 → 等待 SMS → 确认完成
- 批量操作：批量生成、批量执行步骤、批量分配环境
"""
import asyncio
from datetime import datetime
from typing import Optional

from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from app.core.crud import CRUDBase
from app.log import logger
from app.models.gmail_registration import GmailRegistration
from app.models.site_pipeline import Site
from app.models.gmail_account import GmailAccount
from app.models.outlook_account import OutlookAccount
from app.schemas.gmail_registration import GmailRegistrationCreate
from app.services.gmail.registration import gmail_registration_service
from app.settings.config import settings

# Outlook 账号可用状态（只有该状态可被分配）
OUTLOOK_AVAILABLE_STATUS = '正常'

# SMS 等待并发数（轮询为纯等待，可并发以缩短总耗时）
SMS_WAIT_CONCURRENCY = 5

# 从 Outlook 账号同步到注册记录的身份字段映射
_OUTLOOK_IDENTITY_FIELDS = (
    'full_name', 'first_name', 'last_name', 'password',
    'country', 'province_state', 'city', 'zip_code',
    'shipping_address_1', 'shipping_address_2', 'phone',
    'api_url',
)


class GmailRegistrationController(CRUDBase[GmailRegistration, GmailRegistrationCreate, GmailRegistrationCreate]):
    def __init__(self):
        super().__init__(model=GmailRegistration)

    # ── CRUD 基础 ──

    async def create_registration(self, obj_in: GmailRegistrationCreate) -> GmailRegistration:
        """创建注册记录，自动生成 recovery_email；若指定 Outlook 则同步身份信息"""
        data = obj_in.model_dump()
        if not data.get("recovery_email"):
            data["recovery_email"] = f"{data['alias']}@{data['domain']}"
        outlook_account_id = data.pop("outlook_account_id", None)
        reg = await self.create(obj_in=data)
        if outlook_account_id:
            # 分配失败不阻断创建，前端可在列表中重新分配
            await self.assign_outlook(reg.id, outlook_account_id)
            reg = await self.get(id=reg.id)
        return reg

    async def get_by_alias_domain(self, alias: str, domain: str) -> Optional[GmailRegistration]:
        """按别名和域名查询（唯一约束）"""
        return await self.model.filter(alias=alias, domain=domain).first()

    async def list_with_outlook(self, page: int, page_size: int, search: Q = Q(), order: list = None):
        """列表查询，动态填充关联 Outlook 的 api_url（直接读关联，不依赖冗余字段）"""
        total, objs = await self.list(page=page, page_size=page_size, search=search, order=order or ['-id'])
        data = [await obj.to_dict() for obj in objs]

        outlook_ids = {obj.outlook_account_id for obj in objs if obj.outlook_account_id}
        if outlook_ids:
            outlooks = await OutlookAccount.filter(id__in=outlook_ids, is_deleted=False).all()
            outlook_map = {o.id: o for o in outlooks}
            for i, obj in enumerate(objs):
                if obj.outlook_account_id and not data[i].get("api_url"):
                    outlook = outlook_map.get(obj.outlook_account_id)
                    if outlook and outlook.api_url:
                        data[i]["api_url"] = outlook.api_url

        return total, data

    # ── Outlook 邮箱分配 ──

    @staticmethod
    def _apply_outlook_identity(reg: GmailRegistration, acc: Optional[OutlookAccount]) -> None:
        """把 Outlook 账号的身份信息同步到注册记录（解绑时清空）"""
        if acc is None:
            reg.outlook_account_id = None
            reg.outlook_account_username = ''
            reg.recovery_email = f"{reg.alias}@{reg.domain}"
            for field in _OUTLOOK_IDENTITY_FIELDS:
                setattr(reg, field, '')
            return

        reg.outlook_account_id = acc.id
        reg.outlook_account_username = acc.username
        # Outlook 的辅助邮箱作为 Gmail 的恢复邮箱，Outlook 账号作为转发目标
        reg.recovery_email = acc.recovery_email
        if not reg.forward_to:
            reg.forward_to = acc.username
        for field in _OUTLOOK_IDENTITY_FIELDS:
            setattr(reg, field, getattr(acc, field, '') or '')

    async def _available_outlook_query(self, exclude_reg_id: Optional[int] = None):
        """可分配的 Outlook 账号查询：状态正常、未删除、未被其他注册记录占用"""
        occupied_q = self.model.filter(
            is_deleted=False,
            outlook_account_id__isnull=False,
        )
        if exclude_reg_id:
            occupied_q = occupied_q.exclude(id=exclude_reg_id)
        occupied_ids = await occupied_q.values_list('outlook_account_id', flat=True)

        query = OutlookAccount.filter(is_deleted=False, status=OUTLOOK_AVAILABLE_STATUS)
        if occupied_ids:
            query = query.exclude(id__in=[i for i in occupied_ids if i])
        return query

    async def list_available_outlook(self, keyword: str = '', limit: int = 200) -> list[dict]:
        """可分配的 Outlook 账号下拉列表"""
        query = await self._available_outlook_query()
        if keyword:
            query = query.filter(username__contains=keyword)
        accounts = await query.order_by('id').limit(limit)
        return [
            {
                'id': a.id,
                'username': a.username,
                'full_name': a.full_name,
                'status': a.status,
                'country': a.country,
            }
            for a in accounts
        ]

    async def assign_outlook(self, registration_id: int, outlook_account_id: Optional[int]) -> dict:
        """为单条注册记录分配（或解绑）Outlook 邮箱

        一对一独占：目标账号若已被其他记录占用则拒绝。
        分配成功后同步覆盖身份信息。
        """
        reg = await self.get_or_none(id=registration_id)
        if not reg or reg.is_deleted:
            return {"success": False, "error": "注册记录不存在"}

        # 解绑
        if outlook_account_id is None:
            self._apply_outlook_identity(reg, None)
            await reg.save()
            return {"success": True, "message": "已解绑 Outlook 邮箱", "registration": await reg.to_dict()}

        acc = await OutlookAccount.filter(id=outlook_account_id, is_deleted=False).first()
        if not acc:
            return {"success": False, "error": "Outlook 账号不存在或已删除"}
        if acc.status != OUTLOOK_AVAILABLE_STATUS:
            return {"success": False, "error": f"Outlook 账号状态为「{acc.status}」，不可分配"}

        # 独占校验：排除自身
        occupied = await self.model.filter(
            outlook_account_id=outlook_account_id,
            is_deleted=False,
        ).exclude(id=registration_id).first()
        if occupied:
            return {
                "success": False,
                "error": f"该 Outlook 已分配给 {occupied.alias}@{occupied.domain}",
            }

        self._apply_outlook_identity(reg, acc)
        await reg.save()
        return {"success": True, "registration": await reg.to_dict()}

    async def batch_assign_outlook(self, ids: list[int]) -> dict:
        """批量自动分配 Outlook：按顺序取可用账号依次绑定

        Returns:
            {"assigned": N, "skipped": N, "no_account": N, "skip_reasons": [...]}
        """
        assigned, skipped, no_account = 0, 0, 0
        skip_reasons: list[str] = []

        # 一次性取出可用账号池，避免循环内重复查询
        pool = list(await (await self._available_outlook_query()).order_by('id'))
        pool_iter = iter(pool)

        for rid in ids:
            reg = await self.get_or_none(id=rid)
            if not reg or reg.is_deleted:
                skipped += 1
                continue

            if reg.outlook_account_id:
                skipped += 1
                skip_reasons.append(f"[{reg.alias}@{reg.domain}] 已绑定 {reg.outlook_account_username}")
                continue

            acc = next(pool_iter, None)
            if acc is None:
                no_account += 1
                continue

            self._apply_outlook_identity(reg, acc)
            await reg.save()
            assigned += 1

        if no_account:
            skip_reasons.append(f"可用 Outlook 账号不足，{no_account} 条未分配")

        return {
            "assigned": assigned,
            "skipped": skipped,
            "no_account": no_account,
            "skip_reasons": skip_reasons,
        }

    # ── 软删除（级联 Outlook 一并进回收站）──

    async def soft_remove_cascade(self, registration_id: int) -> dict:
        """软删除注册记录，并级联软删除其绑定的 Outlook 账号"""
        reg = await self.get_or_none(id=registration_id)
        if not reg or reg.is_deleted:
            return {"success": False, "error": "注册记录不存在"}

        now = datetime.now()
        outlook_deleted = 0
        async with in_transaction():
            reg.is_deleted = True
            reg.deleted_at = now
            await reg.save()

            if reg.outlook_account_id:
                outlook_deleted = await OutlookAccount.filter(
                    id=reg.outlook_account_id, is_deleted=False
                ).update(is_deleted=True, deleted_at=now)

        return {"success": True, "outlook_deleted": outlook_deleted}

    async def batch_soft_remove_cascade(self, ids: list[int]) -> dict:
        """批量软删除 + 级联 Outlook 软删除"""
        deleted, outlook_deleted, skipped = 0, 0, 0
        for rid in ids:
            result = await self.soft_remove_cascade(rid)
            if result.get("success"):
                deleted += 1
                outlook_deleted += result.get("outlook_deleted", 0)
            else:
                skipped += 1
        return {"deleted": deleted, "outlook_deleted": outlook_deleted, "skipped": skipped}

    async def soft_delete_by_domain(self, domain: str) -> int:
        """软删除指定域名的所有 Gmail 注册记录（配合站点回收站）"""
        registrations = await self.model.filter(domain=domain, is_deleted=False).all()
        count = 0
        for reg in registrations:
            await self.soft_remove(id=reg.id)
            count += 1
        return count

    # ── 流程步骤（单条） ──

    async def create_forwarding(self, registration_id: int) -> dict:
        """步骤1：创建 ImprovMX 转发别名（已废弃，直接使用 HubStudio 创建账号）"""
        reg = await self.get(id=registration_id)
        if not reg:
            return {"success": False, "error": "注册记录不存在"}
        
        return {
            "success": False,
            "error": "ImprovMX 转发步骤已废弃，请直接创建环境后通过 HubStudio 创建账号",
            "registration": await reg.to_dict()
        }

    async def get_phone_number(
        self,
        registration_id: int,
        country_id: Optional[int] = None,
        application_id: Optional[int] = None,
        max_price: Optional[int] = None,
    ) -> dict:
        """步骤3：获取 SMS 号码"""
        reg = await self.get(id=registration_id)
        if not reg:
            return {"success": False, "error": "注册记录不存在"}
        
        if reg.sms_status == "acquired" or reg.sms_request_id:
            return {"success": True, "message": "号码已获取", "registration": await reg.to_dict()}
        
        # 调用 SMSMan
        result = gmail_registration_service.get_phone_number(
            country_id=country_id,
            application_id=application_id,
            max_price=max_price,
        )
        
        if result.get("success"):
            reg.sms_request_id = result.get("request_id")
            reg.sms_phone_number = result.get("phone_number", "")
            reg.sms_status = "acquired"
            reg.registration_status = "registering"
        else:
            reg.sms_status = "failed"
            reg.sms_error = result.get("error", "Unknown error")
        
        await reg.save()
        return {"success": result.get("success"), "registration": await reg.to_dict()}

    async def wait_for_sms(self, registration_id: int, timeout: int = 300, interval: int = 10) -> dict:
        """步骤4：等待 SMS 验证码"""
        reg = await self.get(id=registration_id)
        if not reg:
            return {"success": False, "error": "注册记录不存在"}
        
        if not reg.sms_request_id:
            return {"success": False, "error": "未获取号码"}
        
        if reg.sms_code:
            return {"success": True, "message": "验证码已接收", "registration": await reg.to_dict()}
        
        # 调用 SMSMan 轮询
        result = await gmail_registration_service.wait_for_sms(
            request_id=reg.sms_request_id,
            timeout=timeout,
            interval=interval,
        )
        
        if result.get("success") and result.get("code"):
            reg.sms_code = result["code"]
            reg.sms_status = "code_received"
        else:
            reg.sms_status = "failed"
            reg.sms_error = result.get("error", "Timeout or unknown error")
        
        await reg.save()
        return {"success": result.get("success"), "registration": await reg.to_dict()}

    async def confirm_sms(self, registration_id: int, status: str = "used") -> dict:
        """步骤5：确认 SMS 使用完成"""
        reg = await self.get(id=registration_id)
        if not reg:
            return {"success": False, "error": "注册记录不存在"}
        
        if not reg.sms_request_id:
            return {"success": False, "error": "未获取号码"}
        
        # 调用 SMSMan
        result = gmail_registration_service.confirm_sms(
            request_id=reg.sms_request_id,
            status=status,
        )
        
        if result.get("success"):
            reg.sms_status = "used"
            reg.registration_status = "completed"
            reg.registration_email = f"{reg.alias}@gmail.com"
        
        await reg.save()
        return {"success": result.get("success"), "registration": await reg.to_dict()}

    # ── 批量操作 ──

    async def _run_batch(self, ids: list[int], step, concurrency: int = 1) -> dict:
        """批量执行单条流程步骤

        Args:
            ids: 注册记录 ID 列表
            step: 单条执行协程，签名为 async (registration_id) -> dict
            concurrency: 并发数，1 表示串行（第三方接口限流场景）

        Returns:
            {"ok": N, "fail": N, "errors": [...]}
        """
        semaphore = asyncio.Semaphore(max(concurrency, 1))

        async def _run_one(rid: int) -> tuple[bool, str]:
            async with semaphore:
                try:
                    result = await step(rid)
                    if result.get("success"):
                        return True, ''
                    return False, f"[ID {rid}] {result.get('error') or '执行失败'}"
                except Exception as e:
                    logger.error(f"[gmail_reg] 批量步骤失败: id={rid} err={e}")
                    return False, f"[ID {rid}] {e}"

        results = await asyncio.gather(*[_run_one(rid) for rid in ids])
        errors = [msg for success, msg in results if not success]
        ok = len(results) - len(errors)
        return {"ok": ok, "fail": len(errors), "errors": errors[:20]}

    async def batch_create_forwarding(self, ids: list[int]) -> dict:
        """批量创建转发（已废弃）"""
        return {"ok": 0, "fail": len(ids), "errors": ["ImprovMX 转发步骤已废弃"]}

    async def batch_get_phone(self, ids: list[int]) -> dict:
        """批量获取号码"""
        return await self._run_batch(ids, self.get_phone_number)

    async def batch_wait_sms(self, ids: list[int], timeout: int = 300) -> dict:
        """批量等待短信（轮询为纯等待，可并发以缩短总耗时）"""
        async def _wait(rid: int) -> dict:
            return await self.wait_for_sms(rid, timeout=timeout)

        return await self._run_batch(ids, _wait, concurrency=SMS_WAIT_CONCURRENCY)

    async def batch_confirm_sms(self, ids: list[int]) -> dict:
        """批量确认完成"""
        return await self._run_batch(ids, self.confirm_sms)

    # ── 批量获取待注册站点 ──

    @staticmethod
    def _reset_to_pending(reg: GmailRegistration) -> None:
        """把记录重置为干净的待注册状态（用于复活回收站中的同名记录）"""
        reg.is_deleted = False
        reg.deleted_at = None
        reg.registration_status = 'pending'
        reg.registration_email = ''
        reg.registration_error = ''
        reg.forward_to = ''
        reg.recovery_email = ''
        reg.two_fa_key = ''
        reg.outlook_account_id = None
        reg.outlook_account_username = ''
        for field in _OUTLOOK_IDENTITY_FIELDS:
            setattr(reg, field, '')
        reg.improvmx_alias_id = ''
        reg.improvmx_status = ''
        reg.improvmx_error = ''
        reg.env_id = ''
        reg.env_name = ''
        reg.env_status = ''
        reg.env_error = ''
        reg.sms_request_id = None
        reg.sms_phone_number = ''
        reg.sms_code = ''
        reg.sms_status = ''
        reg.sms_error = ''

    async def batch_fetch_pending_sites(self, alias: str = '') -> dict:
        """同步所有未分配 Gmail 且未删除的站点，为其创建空的待注册记录

        身份信息（姓名、密码、辅助邮箱等）留空，后续通过分配 Outlook 填充。

        Args:
            alias: 邮箱别名前缀，留空则使用配置默认值

        Returns:
            {"created": N, "revived": N, "skipped": N, "failed": N, "skip_reasons": [...]}
        """
        alias = (alias or settings.GMAIL_REGISTRATION_DEFAULT_ALIAS).strip()

        # 已分配 Gmail 的站点 ID（排除）
        assigned_site_ids = await GmailAccount.filter(
            assigned_site_id__isnull=False, is_deleted=False
        ).values_list('assigned_site_id', flat=True)
        assigned_site_ids = [i for i in assigned_site_ids if i]

        # 查询未删除且未分配 Gmail 的站点（不过滤已有环境，允许为已建站点创建 Gmail）
        query = Site.filter(is_deleted=False)
        if assigned_site_ids:
            query = query.exclude(id__in=assigned_site_ids)
        sites = await query.only('id', 'domain').order_by('id')

        # 一次性查出所有已存在的注册记录（避免循环查询）
        domains = [s.domain for s in sites if s.domain]
        existed_map = {
            reg.domain: reg
            for reg in await self.model.filter(alias=alias, domain__in=domains)
        }

        created, revived, skipped, failed = 0, 0, 0, 0
        skip_reasons: list[str] = []

        for site in sites:
            if not site.domain:
                skipped += 1
                skip_reasons.append(f"[站点#{site.id}] 域名为空")
                continue
            try:
                # 从缓存中查找已存在记录
                existed = existed_map.get(site.domain)
                if existed and not existed.is_deleted:
                    skipped += 1
                    continue

                if existed:
                    # 回收站中的同名记录：复活为干净的待注册状态
                    self._reset_to_pending(existed)
                    existed.site_id = site.id  # 绑定站点 ID
                    await existed.save()
                    revived += 1
                    continue

                await self.model.create(
                    alias=alias,
                    domain=site.domain,
                    site_id=site.id,  # 创建时直接绑定站点 ID
                    forward_to='',
                    recovery_email='',
                    registration_status='pending',
                )
                created += 1
            except Exception as e:
                failed += 1
                skip_reasons.append(f"[{site.domain}] 创建失败: {e}")

        return {
            "created": created,
            "revived": revived,
            "skipped": skipped,
            "failed": failed,
            "skip_reasons": skip_reasons[:20],
        }

    # ── 批量分配环境到站点（数据修复工具，不在前端 UI 暴露）──

    async def batch_assign_env_to_sites(self, ids: list[int]) -> dict:
        """将已完成注册的记录环境手动同步到站点（数据修复工具）

        注意：正常流程中，创建环境时会自动同步到站点，此方法仅用于修复历史数据。

        Args:
            ids: 注册记录 ID 列表

        Returns:
            {"assigned": N, "skipped": N, "no_site": N, "skip_reasons": [...]}
        """
        assigned, skipped, no_site = 0, 0, 0
        skip_reasons = []
        
        for rid in ids:
            try:
                reg = await self.get(id=rid)
                if not reg:
                    skipped += 1
                    continue
                
                # 只处理已完成注册且有环境 ID 的记录
                if reg.registration_status != "completed" or not reg.env_id:
                    skipped += 1
                    skip_reasons.append(f"[{reg.alias}@{reg.domain}] 状态={reg.registration_status} env_id={reg.env_id}")
                    continue
                
                # 查找匹配域名的站点（未分配 Gmail 且未创建环境）
                site = await Site.filter(
                    domain=reg.domain,
                    is_deleted=False,
                ).first()
                
                if not site:
                    no_site += 1
                    continue
                
                # 检查站点是否已有 Gmail
                has_gmail = await GmailAccount.filter(assigned_site_id=site.id, is_deleted=False).exists()
                if has_gmail:
                    skipped += 1
                    skip_reasons.append(f"[{site.domain}] 已有 Gmail 分配")
                    continue
                
                # 检查站点是否已有环境
                if site.hub_env_id:
                    skipped += 1
                    skip_reasons.append(f"[{site.domain}] 已有环境 {site.hub_env_id}")
                    continue
                
                # 分配环境 ID 到站点
                site.hub_env_id = reg.env_id
                site.hub_env_name = reg.env_name or ""
                site.pipeline_log = (site.pipeline_log or "") + f"\n[gmail_reg] 分配环境 env_id={reg.env_id}"
                await site.save()
                
                assigned += 1
            except Exception:
                skipped += 1
        
        return {"assigned": assigned, "skipped": skipped, "no_site": no_site, "skip_reasons": skip_reasons}


gmail_registration_controller = GmailRegistrationController()
