import hashlib
import json
import logging
import os
import random
import re
import secrets
import string
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from app.utils.config_reader import get_config
from app.utils.provider_resolver import ProviderResolver
from app.models.site_pipeline import Site

_log = logging.getLogger(__name__)


# ========================= 安全日志工具 =========================

def mask_secret(value: str, keep: int = 4) -> str:
    """脱敏：保留首尾各 keep 位，中间用 *** 替换"""
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "***"
    return value[:keep] + "***" + value[-keep:]


def safe_log_data(data: Any, max_len: int = 1200) -> str:
    """递归隐藏 token/password/secret 等敏感字段，生成安全日志文本"""
    secret_keys = {"api_key", "apikey", "token", "password", "passwd", "secret",
                   "consumer_secret", "PANEL_DB_PASSWORD", "PANEL_DB_USER_PASSWORD",
                   "WORDPRESS_ADMIN_PASSWORD"}

    def scrub(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if str(k).lower() in {x.lower() for x in secret_keys} or \
                   any(x in str(k).lower() for x in ["password", "secret", "token"]):
                    out[k] = mask_secret(str(v))
                else:
                    out[k] = scrub(v)
            return out
        if isinstance(obj, list):
            return [scrub(x) for x in obj]
        return obj

    try:
        text = json.dumps(scrub(data), ensure_ascii=False, default=str)
    except Exception:
        text = str(data)
    return text[:max_len] + ("..." if len(text) > max_len else "")


def normalize_domain(domain: str) -> str:
    """标准化域名：去协议、去路径、去尾部点号，验证格式"""
    domain = (domain or "").strip().lower()
    domain = re.sub(r"^https?://", "", domain)
    domain = domain.split("/")[0].strip().strip(".")
    if not re.match(r"^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}$", domain):
        raise ValueError(f"非法域名: {domain}")
    return domain


def safe_alias(domain: str) -> str:
    """生成唯一应用别名：{域名前缀}-{hash6}-{时间戳}{随机数}"""
    prefix = re.sub(r"[^a-zA-Z0-9-]", "-", domain).strip("-")[:30]
    domain_hash = hashlib.md5(domain.encode("utf-8")).hexdigest()[:6]
    unique = f"{int(time.time())}{secrets.randbelow(1000):03d}"
    return f"{prefix}-{domain_hash}-{unique}"


def wait_until(fn: Callable[[], Any], timeout: int, interval: int = 5, desc: str = "等待") -> Any:
    """通用轮询工具：循环调用 fn() 直到返回非空/非 None，超时则抛 TimeoutError"""
    start = time.time()
    last = None
    while time.time() - start < timeout:
        try:
            last = fn()
            if last:
                return last
        except Exception as exc:
            _log.debug("%s 轮询异常：%s", desc, exc)
        time.sleep(interval)
    raise TimeoutError(f"{desc} 超时，最后结果：{last}")


def parse_env_text(content: str) -> Dict[str, str]:
    """解析 .env 风格 key=value 文本"""
    result: Dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        result[k.strip()] = v.strip().strip("'").strip('"')
    return result


def random_str(length: int = 18, punctuation: bool = False) -> str:
    """密码安全随机字符串"""
    chars = string.ascii_letters + string.digits
    if punctuation:
        chars += "!@#$%^*()_+-="
    return "".join(secrets.choice(chars) for _ in range(length))


def _provider_value(cfgs: Dict[str, Any], op_key: str, plain_key: str, default: Any = None) -> Any:
    """兼容 provider 的 OP_* 与小写业务键名。"""
    value = cfgs.get(op_key)
    if value is None or value == '':
        value = cfgs.get(plain_key)
    return default if value is None or value == '' else value


def replace_domain_in_sql(content: str, old_domain: str, new_domain: str) -> str:
    """SQL 级别域名替换，同时修正 serialize 长度字段"""
    content = content.replace(old_domain, new_domain)

    def fix_serialize_len(m: re.Match) -> str:
        val = m.group(2)
        return f's:{len(val.encode("utf-8"))}:"{val}";'

    content = re.sub(r's:(\d+):"((?:[^"\\]|\\.)*)";', fix_serialize_len, content)
    return content
