"""create_env / update_env 共享工具"""

# ── 备注字段顺序 ──
# LastName-FirstName-Address-City-State-Zip-Country-improvmx_account-improvmx_password-Email-API_URL-domain-gmail_account-gmail_password
# remark_fields 中的字段（从 GmailRegistration/GmailAccount 读取）
REMARK_FIELDS_MAP = [
    "LastName",
    "FirstName",
    "ShippingAddress_1",
    "City",
    "Province/State",
    "Zip_code",
    "Country",
]

# payload 顶层字段
PAYLOAD_FIELDS_MAP = [
    "outlook_username",        # ImprovMX 账号（Outlook 邮箱）
    "outlook_password",        # ImprovMX 密码（Outlook 密码）
    "Recovery_Email",          # 恢复邮箱
    "API_URL",                 # API 地址
    "domain",                  # 域名
    "gmail_account",           # Gmail 注册账号（alias@domain.com）
    "gmail_password",          # Gmail 注册密码（硬编码 Dzht1008aaa）
]


def build_remark(payload: dict) -> str:
    """构建环境备注文本（不包含字段名，仅值，用 ---- 分隔）
    
    字段顺序：LastName-FirstName-Address-City-State-Zip-Country-improvmx_account-improvmx_password-Email-API_URL-domain-gmail_account-gmail_password
    
    说明：
    - improvmx_account/improvmx_password: Outlook 账号密码，用于注册 ImprovMX
    - gmail_account/gmail_password: alias@domain.com / Dzht1008aaa，用于 Gmail 注册
    """
    parts = []
    remark_fields = payload.get("remark_fields", {})
    
    # 1. 从 remark_fields 读取基础字段
    for field_key in REMARK_FIELDS_MAP:
        val = remark_fields.get(field_key, "")
        if val:
            val_str = str(val).strip()
            if val_str:
                parts.append(val_str)
    
    # 2. 从 payload 顶层读取额外字段
    for field_key in PAYLOAD_FIELDS_MAP:
        val = ""
        
        # Gmail 账号：优先使用 registration_email，否则构造 alias@domain
        if field_key == "gmail_account":
            val = payload.get("registration_email", "")
            if not val:
                alias = payload.get("alias", "")
                domain = payload.get("domain", "")
                if alias and domain:
                    val = f"{alias}@{domain}"
        # Gmail 密码：硬编码
        elif field_key == "gmail_password":
            val = "Dzht1008aaa"
        # Recovery_Email 优先从 remark_fields 读取
        elif field_key == "Recovery_Email" and remark_fields:
            val = remark_fields.get(field_key, "") or payload.get(field_key, "")
        # 其他字段从 payload 读取
        else:
            val = payload.get(field_key, "")
        
        if val:
            val_str = str(val).strip()
            if val_str:
                parts.append(val_str)
    
    return "----".join(parts) if parts else ""


def build_container_name(domain: str) -> str:
    return f"{domain}/wp-admin"
