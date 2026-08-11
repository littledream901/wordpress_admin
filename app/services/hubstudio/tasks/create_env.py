"""统一创建环境 (create_env / create_gmail_env)

支持两种模式：
- 站点模式：从 Site 表读取域名，用于建站流程
- Gmail 模式：从 GmailRegistration 读取 alias + domain + 身份信息，用于邮箱注册流程
"""

from app.core.exceptions import HubStudioError
from app.utils.config_reader import get_config
from ..runtime import HubStudioRuntime
from ._common import build_container_name, build_remark, REMARK_FIELD_MAP


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


# Gmail 模式扁平字段顺序（与 REMARK_FIELD_MAP 对齐）
_FLAT_REMARK_FIELDS = (
    "shipping_address_1",
    "city",
    "province_state",
    "zip_code",
    "country",
    "recovery_email",
)


def _build_remark_for_create(payload: dict, domain: str) -> str:
    """构建环境备注

    取值优先级：
    1. payload["remark_fields"]（站点派发链路统一注入）
    2. payload 扁平身份字段（Gmail 注册链路直接传入）
    3. alias@domain
    4. domain
    """
    remark = build_remark(payload)
    if remark:
        return remark

    parts = [
        str(payload[field]).strip()
        for field in _FLAT_REMARK_FIELDS
        if str(payload.get(field, "")).strip()
    ]
    if parts:
        return " , ".join(parts)

    alias = payload.get("alias", "")
    if alias:
        return f"{alias}@{domain}"
    return domain or "unknown"


def execute_create_env(executor, job: dict, payload: dict) -> dict:
    """统一创建环境执行器（兼容 create_env 和 create_gmail_env）"""
    # 读取域名（Gmail 模式优先用 domain，站点模式从 job 读取）
    domain = payload.get("domain") or job.get("domain", "")
    alias = payload.get("alias", "")
    is_gmail_mode = bool(alias)

    if not domain:
        return {"status": "failed", "error": "domain is required"}

    mode_label = "create_gmail_env" if is_gmail_mode else "create_env"
    executor.logger.info(f"[{mode_label}] 开始: domain={domain}, alias={alias or 'N/A'}")
    
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
            container_name = existed.get("containerName", "")
            executor.logger.info(f"[{mode_label}] 环境已存在: containerCode={container_code}")
            return {
                "status": "success",
                "action": "exists",
                "env_id": container_code,
                "containerCode": container_code,
                "containerName": container_name,
                "domain": domain,
                "raw": existed,
            }
    except Exception as e:
        executor.logger.warning(f"查重跳过: {e}")

    # 构建备注
    remark = _build_remark_for_create(payload, domain)
    executor.logger.info(f"[{mode_label}] remark={remark}")

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
        executor.logger.info(f"[{mode_label}] 创建成功: env_id={env_id}")
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
        executor.logger.error(f"[{mode_label}] 创建失败: {e}")
        return {"status": "failed", "error": str(e)}
