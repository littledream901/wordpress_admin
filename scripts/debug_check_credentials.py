"""调试脚本：检查站点注册记录、任务 payload 和凭证传递链路"""
import asyncio
import json
import sys
from pathlib import Path

# 将项目根目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from tortoise import Tortoise

async def main():
    from app.settings import TORTOISE_ORM
    await Tortoise.init(config=TORTOISE_ORM)
    
    from app.models.site_pipeline import Site, HubStudioJob
    from app.models.gmail_registration import GmailRegistration
    from app.models.outlook_account import OutlookAccount
    
    domain = "wayasfair.shop"
    
    # 1. 检查站点
    site = await Site.filter(domain=domain).first()
    if not site:
        print(f"❌ 站点 {domain} 不存在")
        return
    
    print(f"✅ 站点: {site.id} | {site.domain} | hub_env_id={site.hub_env_id}")
    
    # 2. 检查该域名全部注册记录，确认实际状态（支持 env_created 和 completed）
    registrations = await GmailRegistration.filter(
        domain=domain,
        is_deleted=False,
    ).order_by("-id")
    
    registration = next(
        (item for item in registrations
         if item.registration_status in ["env_created", "completed"]),
        None,
    )
    
    if registrations:
        print(f"✅ 该域名注册记录数: {len(registrations)}")
        for item in registrations:
            outlook_username = ""
            if item.outlook_account_id:
                outlook = await OutlookAccount.filter(id=item.outlook_account_id).first()
                outlook_username = outlook.username if outlook else "(Outlook不存在)"
            elif item.outlook_account_username:
                outlook_username = item.outlook_account_username
            
            print(
                f"   - id={item.id}, status={item.registration_status}, "
                f"site_id={item.site_id}, email={item.registration_email or '(空)'}, "
                f"password={'有' if item.password else '空'}, "
                f"outlook={outlook_username or '(空)'}"
            )
        if registration:
            print(f"✅ 存在可用于创建账号的注册记录: {registration.id} ({registration.registration_status})")
        else:
            print("❌ 没有 env_created 或 completed 状态的注册记录")
    else:
        print(f"❌ 该域名没有注册记录")
    
    # 检查 Outlook 账号
    if registration and registration.outlook_account_id:
        outlook = await OutlookAccount.filter(id=registration.outlook_account_id).first()
        if outlook:
            print(f"✅ Outlook 账号: {outlook.username}")
            print(f"   - password: {'有' if outlook.password else '空'}")
        else:
            print("❌ Outlook 账号不存在")
    elif registration:
        print("⚠️  可用注册记录未分配 Outlook 账号")
    
    # 3. 检查最近的 create_account 任务
    job = await HubStudioJob.filter(
        domain=domain,
        job_type="create_account"
    ).order_by("-id").first()
    
    if job:
        print(f"\n✅ 最新 create_account 任务: {job.id}")
        print(f"   - status: {job.status}")
        print(f"   - created_at: {job.created_at}")
        
        payload = json.loads(job.payload_json or "{}")
        print(f"   - payload keys: {list(payload.keys())}")
        
        # 检查四类凭证
        creds = {
            "improvmx": ("improvmx_username", "improvmx_password"),
            "workspace": ("workspace_username", "workspace_password"),
            "personal_gmail": ("personal_gmail_username", "personal_gmail_password", "personal_gmail_2fa_key"),
            "wordpress": ("admin_account_name", "admin_account_password"),
        }
        
        print("\n📋 Payload 凭证检查:")
        for name, keys in creds.items():
            values = [payload.get(k, "") for k in keys]
            has_data = any(v for v in values)
            status = "✅" if has_data else "❌"
            print(f"   {status} {name}: {keys} -> {['***' if v else '(空)' for v in values]}")
        
        # 检查旧字段兼容
        old_keys = ["gmail_username", "gmail_password", "gmail_2fa_key"]
        old_values = [payload.get(k, "") for k in old_keys]
        has_old = any(v for v in old_values)
        print(f"   {'✅' if has_old else '❌'} 旧兼容字段: {old_keys} -> {['***' if v else '(空)' for v in old_values]}")
    else:
        print(f"\n❌ 未找到 create_account 任务")
    
    await Tortoise.close_connections()

if __name__ == "__main__":
    asyncio.run(main())
