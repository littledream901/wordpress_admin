"""Nginx Lua 注入逻辑校验（对比原脚本行为）

验证点：
1. 首次部署（无 Fangyu 配置）不会误删站点自有指令
2. 注入后配置能通过逻辑校验
3. 重复部署幂等（不产生重复块）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.gateway_defense.nginx_lua import (  # noqa: E402
    _has_fangyu_config,
    _inject_access,
    _inject_body_filter,
    _inject_variables,
    _remove_old_fangyu_config,
    _render_blocks,
    _validate_nginx_config_logic,
)

DOMAIN = "example.com"

# 模拟 1Panel 生成的站点配置（含站点自有的 real_ip 与 proxy_set_header）
BASE_CONFIG = """server {
    listen 80;
    listen 443 ssl http2;
    server_name example.com www.example.com;
    index index.php index.html;
    root /www/sites/example.com/index;

    set_real_ip_from 10.1.0.0/16;
    real_ip_header X-Real-IP;

    ssl_certificate /www/sites/example.com/ssl/fullchain.pem;
    ssl_certificate_key /www/sites/example.com/ssl/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header Accept-Encoding "";
    }

    location ~ \\.php$ {
        fastcgi_pass unix:/tmp/php.sock;
    }

    access_log /www/sites/example.com/log/access.log;
}
"""


def _deploy(config: str) -> str:
    """执行一次完整注入流程"""
    variables, access, body_filter = _render_blocks(
        DOMAIN, "12", "site_abc123", "a" * 48, "https://gw.test.com"
    )
    result = _remove_old_fangyu_config(config)
    result = _inject_variables(result, variables)
    result = _inject_access(result, access)
    result = _inject_body_filter(result, body_filter)
    return result


def test_first_deploy_preserves_site_directives():
    """首次部署不应删除站点自有的 real_ip / proxy_set_header 指令"""
    # BASE_CONFIG 含站点自有的 set_real_ip_from（非 Fangyu），不应触发清理
    assert _has_fangyu_config(BASE_CONFIG) is False, "站点自有 real_ip 不应被识别为 Fangyu 配置"
    assert _remove_old_fangyu_config(BASE_CONFIG) == BASE_CONFIG, "首次部署必须原样返回"

    deployed = _deploy(BASE_CONFIG)
    assert "proxy_pass http://127.0.0.1:8080;" in deployed
    assert "fastcgi_pass unix:/tmp/php.sock;" in deployed
    assert "ssl_certificate_key" in deployed
    print("[PASS] 首次部署保留站点自有指令")


def test_injection_passes_validation():
    """注入结果必须通过逻辑校验"""
    deployed = _deploy(BASE_CONFIG)
    valid, errors = _validate_nginx_config_logic(deployed, DOMAIN)
    assert valid, f"注入后校验失败: {errors}"

    assert f"access_by_lua_file /www/sites/{DOMAIN}/lua/defense.lua;" in deployed
    assert "body_filter_by_lua_block" in deployed
    assert f"include /www/sites/{DOMAIN}/lua/fangyu_real_ip.conf;" in deployed
    for var in ("$fangyu_gateway_url", "$fangyu_site_id", "$fangyu_site_key", "$fangyu_site_secret"):
        assert var in deployed, f"缺少变量 {var}"
    print("[PASS] 注入结果通过逻辑校验")


def test_access_inside_location_block():
    """access_by_lua_file 必须落在 location / 块内部"""
    deployed = _deploy(BASE_CONFIG)
    lines = deployed.split("\n")

    loc_idx = next(i for i, l in enumerate(lines) if l.strip() == "location / {")
    access_idx = next(i for i, l in enumerate(lines) if "access_by_lua_file" in l)

    # 找 location / 块的闭合行
    depth = 0
    close_idx = -1
    for i in range(loc_idx, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth <= 0:
            close_idx = i
            break

    assert loc_idx < access_idx < close_idx, (
        f"access_by_lua_file 位置错误: location={loc_idx} access={access_idx} close={close_idx}"
    )

    bf_idx = next(i for i, l in enumerate(lines) if "body_filter_by_lua_block" in l)
    assert loc_idx < bf_idx < close_idx, "body_filter 未落在 location / 块内"
    print("[PASS] Lua 指令落在 location / 块内")


def test_idempotent_redeploy():
    """重复部署不应产生重复配置块"""
    once = _deploy(BASE_CONFIG)
    twice = _deploy(once)

    assert twice.count("$fangyu_gateway_url") == 1, f"变量重复 {twice.count('$fangyu_gateway_url')} 次"
    assert twice.count("access_by_lua_file") == 1, "access 指令重复"
    assert twice.count("body_filter_by_lua_block") == 1, "body_filter 重复"
    assert twice.count("fangyu_real_ip.conf") == 1, "real_ip include 重复"

    valid, errors = _validate_nginx_config_logic(twice, DOMAIN)
    assert valid, f"二次部署后校验失败: {errors}"
    print("[PASS] 重复部署幂等")


def test_validation_catches_missing_injection():
    """注入失败时校验必须报错"""
    valid, errors = _validate_nginx_config_logic(BASE_CONFIG, DOMAIN)
    assert not valid, "未注入的配置不应通过校验"
    assert len(errors) > 0
    print(f"[PASS] 校验捕获未注入配置 ({len(errors)} 个错误)")


if __name__ == "__main__":
    test_first_deploy_preserves_site_directives()
    test_injection_passes_validation()
    test_access_inside_location_block()
    test_idempotent_redeploy()
    test_validation_catches_missing_injection()
    print("\n全部通过")
