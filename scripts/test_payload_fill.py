"""测试 _enrich_create_account_payload 的实际填充结果"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tortoise import Tortoise
from app.settings.config import settings
from app.models.site_pipeline import Site
from app.services.hubstudio_service import HubStudioOrchestrationService


async def test():
    await Tortoise.init(config=settings.TORTOISE_ORM)
    
    domain = "wayasfair.shop"
    site = await Site.filter(domain=domain).first()
    
    if not site:
        print(f"❌ 站点不存在: {domain}")
        await Tortoise.close_connections()
        return
    
    print(f"{'='*60}")
    print(f"测试站点: {domain} (ID={site.id})")
    print(f"{'='*60}\n")
    
    # 调用实际的 payload 填充方法
    service = HubStudioOrchestrationService()
    payload = {}
    enriched_payload = await service._enrich_create_account_payload(payload, site)
    
    print("📦 填充后的 Payload:")
    print(f"{'─'*60}")
    
    # ImprovMX
    print(f"\n1️⃣  ImprovMX 凭证:")
    print(f"   improvmx_username: {enriched_payload.get('improvmx_username', '(空)')}")
    print(f"   improvmx_password: {'***' if enriched_payload.get('improvmx_password') else '(空)'}")
    
    # Gmail Workspace
    print(f"\n2️⃣  Gmail Workspace 凭证:")
    print(f"   workspace_username: {enriched_payload.get('workspace_username', '(空)')}")
    print(f"   workspace_password: {'***' if enriched_payload.get('workspace_password') else '(空)'}")
    
    # Gmail 个人账号
    print(f"\n3️⃣  Gmail 个人账号凭证:")
    print(f"   personal_gmail_username: {enriched_payload.get('personal_gmail_username', '(空)')}")
    print(f"   personal_gmail_password: {'***' if enriched_payload.get('personal_gmail_password') else '(空)'}")
    print(f"   personal_gmail_2fa_key: {'***' if enriched_payload.get('personal_gmail_2fa_key') else '(空)'}")
    
    # 兼容旧字段
    print(f"\n4️⃣  兼容旧字段:")
    print(f"   gmail_username: {enriched_payload.get('gmail_username', '(空)')}")
    print(f"   gmail_password: {'***' if enriched_payload.get('gmail_password') else '(空)'}")
    print(f"   gmail_2fa_key: {'***' if enriched_payload.get('gmail_2fa_key') else '(空)'}")
    
    # 备注字段
    remark_fields = enriched_payload.get('remark_fields', {})
    print(f"\n5️⃣  备注字段:")
    if remark_fields:
        for key, value in remark_fields.items():
            print(f"   {key}: {value}")
    else:
        print(f"   (无)")
    
    print(f"\n{'='*60}")
    print("✅ Payload 填充完成")
    print(f"{'='*60}")
    
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(test())
