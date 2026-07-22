"""create_env / update_env 共享工具"""

# ── 备注来源字段 ──
REMARK_FIELD_MAP = [
    ("Address", "ShippingAddress_1"),
    ("City", "City"),
    ("State", "Province/State"),
    ("Zip", "Zip_code"),
    ("Country", "Country"),
    ("Email", "Recovery_Email"),
]


def build_remark(payload: dict) -> str:
    """构建环境备注文本"""
    remark_fields = payload.get("remark_fields", {})
    if not remark_fields:
        return ""

    parts = []
    for _label, field_key in REMARK_FIELD_MAP:
        val = remark_fields.get(field_key, "")
        if val:
            val_str = str(val).strip()
            if val_str:
                parts.append(val_str)

    return " , ".join(parts) if parts else ""


def build_container_name(domain: str) -> str:
    return f"{domain}/wp-admin"
