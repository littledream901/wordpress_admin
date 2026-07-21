"""创建环境 (create_env)"""

from app.core.exceptions import HubStudioError
from app.utils.config_reader import get_config
from ..runtime import HubStudioRuntime


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


def get_tag_code_by_name(runtime: HubStudioRuntime, target_tag_name: str) -> tuple:
    """返回 (tagCode, tagName)"""
    resp = runtime.ensure_client().get_group_list()
    for item in resp.get("data", []):
        if item.get("tagName") == target_tag_name:
            return item["tagCode"], item["tagName"]
    raise HubStudioError("get group", detail=f"tag not found: {target_tag_name}")


def get_existing_env_by_domain(runtime: HubStudioRuntime, domain: str, tag_code: str):
    """查重：根据域名查找已存在的环境"""
    client = runtime.ensure_client()
    page = 1
    container_name = build_container_name(domain)
    while True:
        resp = client.get_env_list(current=page, size=200, tagCode=tag_code)
        env_list = resp.get("data", {}).get("list", [])
        if not env_list:
            break
        for item in env_list:
            if item.get("containerName") == container_name:
                return item
        if len(env_list) < 200:
            break
        page += 1
    return None


def execute_create_env(executor, job: dict, payload: dict) -> dict:
    domain = payload.get("domain", job.get("domain", ""))
    login_url = payload.get("login_url", "")

    if not domain:
        return {"status": "failed", "error": "domain is required"}

    executor.logger.info(f"[create_env] 开始: domain={domain}")
    executor.rt.start_connector()
    client = executor.rt.ensure_client()

    # 获取分组 code
    target_tag_name = get_config("HUBSTUDIO_BUSINESS_GROUP_NAME", "")
    tag_code = None
    tag_name = target_tag_name
    try:
        tag_code, tag_name = get_tag_code_by_name(executor.rt, target_tag_name)
        executor.logger.info(f"分组 [{target_tag_name}] tagCode={tag_code} tagName={tag_name}")
    except Exception:
        tag_code = executor.rt.group_code

    # 查重
    try:
        existed = get_existing_env_by_domain(executor.rt, domain, tag_code)
        if existed:
            container_code = existed.get("containerCode")
            executor.logger.info(f"[create_env] 环境已存在: containerCode={container_code}")
            return {
                "status": "success",
                "action": "exists",
                "env_id": container_code,
                "domain": domain,
                "raw": existed,
            }
    except Exception as e:
        executor.logger.warning(f"查重跳过: {e}")

    # 构建备注：使用 REMARK_FIELD_MAP（地址+Recovery_Email），创建时暂无 Gmail 信息则用域名
    remark = build_remark(payload) or domain or "unknown"
    executor.logger.info(f"[create_env] remark={remark}")

    # 创建
    container_name = build_container_name(domain)
    params = {
        "containerName": container_name,
        "tagName": tag_name,
        "proxyTypeName": "不使用代理",
        "coreVersion": executor.rt.kernel_version,
        "remark": remark,
    }
    try:
        resp = client.create_env(**params)
        data = resp.get("data", {})
        env_id = data.get("containerCode")
        executor.logger.info(f"[create_env] 创建成功: env_id={env_id}")
        return {
            "status": "success",
            "action": "created",
            "env_id": env_id,
            "containerCode": env_id,
            "containerName": container_name,
            "domain": domain,
            "raw": resp,
        }
    except Exception as e:
        executor.logger.error(f"[create_env] 创建失败: {e}")
        return {"status": "failed", "error": str(e)}
