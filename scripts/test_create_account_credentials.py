"""测试 wayasfair.shop 的创建账号凭证组装逻辑"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from tortoise import Tortoise
from app.settings.config import settings
from app.models.site_pipeline import Site
from app.models.gmail_account import GmailAccount
from app.models.gmail_registration import GmailRegistration
from app.models.outlook_account import OutlookAccount


async def test_credentials():
    """测试 wayasfair.shop 站点的账号凭证"""
    
    # 初始化数据库
    await Tortoise.init(config=settings.TORTOISE_ORM)
    
    domain = "wayasfair.shop"
    
    print(f"\n{'='*60}")
    print(f"测试域名: {domain}")
    print(f"{'='*60}\n")
    
    # 1. 查询站点
    site = await Site.filter(domain=domain).first()
    if not site:
        print(f"❌ 站点不存在: {domain}")
        await Tortoise.close_connections()
        return
    
    print(f"✅ 站点信息:")
    print(f"   ID: {site.id}")
    print(f"   Domain: {site.domain}")
    print(f"   Hub Env ID: {site.hub_env_id}")
    print(f"   Hub Account ID: {site.hub_account_id}")
    print(f"   Login URL: {site.login_url}")
    
    # 2. 查询 GmailAccount (assigned_site_id)
    print(f"\n{'─'*60}")
    print("📧 查询 GmailAccount (assigned_site_id):")
    gmail = await GmailAccount.filter(assigned_site_id=site.id, is_deleted=False).first()
    if gmail:
        print(f"   ✅ 找到已分配的 Gmail 账号:")
        print(f"      ID: {gmail.id}")
        print(f"      Username: {gmail.username}")
        print(f"      Password: {'***' if gmail.password else '(空)'}")
        print(f"      2FA Key: {'***' if gmail.two_fa_key else '(空)'}")
    else:
        print(f"   ⚠️  未找到已分配的 Gmail 账号 (assigned_site_id={site.id})")
    
    # 3. 查询 GmailRegistration (site_id)
    print(f"\n{'─'*60}")
    print("📝 查询 GmailRegistration (site_id):")
    registration = await GmailRegistration.filter(
        site_id=site.id,
        registration_status__in=["env_created", "completed"],
        is_deleted=False,
    ).order_by("-id").first()
    
    if registration:
        print(f"   ✅ 找到注册记录 (site_id 匹配):")
        print(f"      ID: {registration.id}")
        print(f"      Status: {registration.registration_status}")
        print(f"      Registration Email: {registration.registration_email}")
        print(f"      Password: {'***' if registration.password else '(空)'}")
        print(f"      2FA Key: {'***' if registration.two_fa_key else '(空)'}")
        print(f"      Outlook Account ID: {registration.outlook_account_id}")
    else:
        # 尝试按 domain 查询
        print(f"   ⚠️  未找到注册记录 (site_id={site.id})")
        print(f"\n   尝试按 domain 查询:")
        registration = await GmailRegistration.filter(
            domain=site.domain,
            registration_status__in=["env_created", "completed"],
            is_deleted=False,
        ).order_by("-id").first()
        
        if registration:
            print(f"   ✅ 找到注册记录 (domain 匹配):")
            print(f"      ID: {registration.id}")
            print(f"      Status: {registration.registration_status}")
            print(f"      Registration Email: {registration.registration_email}")
            print(f"      Password: {'***' if registration.password else '(空)'}")
            print(f"      Site ID: {registration.site_id} (不匹配当前站点)")
        else:
            print(f"   ❌ 未找到任何注册记录 (domain={domain})")
    
    # 4. 查询 OutlookAccount
    if registration and registration.outlook_account_id:
        print(f"\n{'─'*60}")
        print("📮 查询 OutlookAccount:")
        outlook = await OutlookAccount.filter(
            id=registration.outlook_account_id,
            is_deleted=False,
        ).first()
        if outlook:
            print(f"   ✅ 找到 Outlook 账号:")
            print(f"      ID: {outlook.id}")
            print(f"      Username: {outlook.username}")
            print(f"      Password: {'***' if outlook.password else '(空)'}")
        else:
            print(f"   ❌ Outlook 账号不存在 (ID={registration.outlook_account_id})")
    
    # 5. 模拟凭证组装逻辑
    print(f"\n{'='*60}")
    print("🔑 凭证组装结果 (模拟 _enrich_create_account_payload):")
    print(f"{'='*60}\n")
    
    outlook_username = ""
    outlook_password = ""
    if registration and registration.outlook_account_id:
        outlook = await OutlookAccount.filter(
            id=registration.outlook_account_id,
            is_deleted=False,
        ).first()
        if outlook:
            outlook_username = outlook.username or ""
            outlook_password = outlook.password or ""
    
    personal_username = ""
    personal_password = ""
    personal_2fa_key = ""
    workspace_username = ""
    workspace_password = ""
    
    # 优先使用已分配的 GmailAccount
    if gmail and gmail.username and gmail.password:
        personal_username = gmail.username
        personal_password = gmail.password
        personal_2fa_key = gmail.two_fa_key or ""
    
    # Gmail Workspace 和个人 Gmail 账号：支持 env_created 和 completed 状态
    if registration:
        # completed 状态：使用注册成功的 Gmail 凭证
        if registration.registration_status == "completed" and registration.registration_email and registration.password:
            workspace_username = registration.registration_email
            workspace_password = registration.password
            # 如果没有分配 GmailAccount，使用注册邮箱作为个人 Gmail
            if not personal_username:
                personal_username = registration.registration_email
                personal_password = registration.password
                personal_2fa_key = registration.two_fa_key or ""
        # env_created 状态：使用 alias@domain 构造 Gmail 凭证
        elif registration.registration_status == "env_created" and registration.alias and registration.domain and registration.password:
            # Gmail Workspace 和个人账号都使用 alias@domain
            workspace_username = f"{registration.alias}@{registration.domain}"
            workspace_password = registration.password
            if not personal_username:
                personal_username = f"{registration.alias}@{registration.domain}"
                personal_password = registration.password
                personal_2fa_key = registration.two_fa_key or ""
    
    print(f"1️⃣  ImprovMX 账号:")
    print(f"    Username: {outlook_username or '(无)'}")
    print(f"    Password: {'***' if outlook_password else '(无)'}")
    print(f"    状态: {'✅ 可创建' if outlook_username and outlook_password else '❌ 跳过'}")
    
    print(f"\n2️⃣  Gmail Workspace 账号:")
    print(f"    Username: {workspace_username or '(无)'}")
    print(f"    Password: {'***' if workspace_password else '(无)'}")
    print(f"    状态: {'✅ 可创建' if workspace_username and workspace_password else '❌ 跳过'}")
    
    print(f"\n3️⃣  Gmail 个人账号:")
    print(f"    Username: {personal_username or '(无)'}")
    print(f"    Password: {'***' if personal_password else '(无)'}")
    print(f"    2FA Key: {'***' if personal_2fa_key else '(无)'}")
    print(f"    状态: {'✅ 可创建' if personal_username and personal_password else '❌ 跳过'}")
    
    print(f"\n4️⃣  WordPress 后台账号:")
    print(f"    Login URL: {site.login_url}")
    print(f"    状态: {'✅ 可创建' if site.login_url else '❌ 跳过'}")
    
    # 6. 诊断建议
    print(f"\n{'='*60}")
    print("💡 诊断建议:")
    print(f"{'='*60}\n")
    
    if not gmail and not registration:
        print("⚠️  问题: 既没有 GmailAccount，也没有 GmailRegistration")
        print("   解决方案:")
        print("   1. 手动分配一个 GmailAccount 到该站点 (assigned_site_id)")
        print("   2. 或者创建 GmailRegistration 记录并绑定 site_id")
    elif gmail and not (gmail.username and gmail.password):
        print("⚠️  问题: GmailAccount 存在但缺少凭证")
        print(f"   请检查 GmailAccount ID={gmail.id} 的 username 和 password 字段")
    elif registration:
        if registration.registration_status == "env_created":
            if registration.alias and registration.domain and registration.password:
                print(f"✅ env_created 状态：使用 {registration.alias}@{registration.domain} 作为 Gmail 个人账号凭证")
            else:
                print("⚠️  问题: env_created 状态但缺少 alias/domain/password")
                print("   无法创建 Gmail 个人账号")
        elif registration.registration_status == "completed":
            if registration.registration_email and registration.password:
                print("✅ completed 状态：使用注册邮箱作为 Gmail 凭证")
            else:
                print("⚠️  问题: completed 状态但缺少 registration_email 或 password")
                print(f"   请检查 GmailRegistration ID={registration.id}")
        else:
            print(f"⚠️  问题: GmailRegistration 状态为 {registration.registration_status}")
            print("   需要 'env_created' 或 'completed' 状态")
    
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(test_credentials())
