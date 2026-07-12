"""配置校验和 Settings 单元测试"""

import os

import pytest


# ══════════════════════════════════════════════════════════════════════════
#  Settings 字段默认值测试（使用 monkeypatch.setenv 隔离环境变量）
# ══════════════════════════════════════════════════════════════════════════

def test_debug_defaults_to_false(monkeypatch):
    """P0: DEBUG 默认应为 False"""
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DEFAULT_PASSWORD", raising=False)
    from app.settings.config import Settings
    s = Settings(_env_file=None)
    assert s.DEBUG is False, "生产安全：DEBUG 必须默认 False"


def test_secret_key_defaults_to_empty(monkeypatch):
    """P0: SECRET_KEY 默认应为空字符串"""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("DEFAULT_PASSWORD", raising=False)
    from app.settings.config import Settings
    s = Settings(_env_file=None)
    assert s.SECRET_KEY == "", "安全：SECRET_KEY 不应有硬编码默认值"


def test_default_password_defaults_to_empty(monkeypatch):
    """P0: DEFAULT_PASSWORD 默认应为空"""
    monkeypatch.delenv("DEFAULT_PASSWORD", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)
    from app.settings.config import Settings
    s = Settings(_env_file=None)
    assert s.DEFAULT_PASSWORD == "", "安全：DEFAULT_PASSWORD 不应有硬编码默认值"



# ══════════════════════════════════════════════════════════════════════════
#  _validate_settings 测试（使用 monkenv 设置环境变量 +
#  importlib.reload 重新加载 settings）
# ══════════════════════════════════════════════════════════════════════════

class TestValidateSettings:
    """测试启动配置校验 — 直接 patch settings 对象属性"""

    def test_empty_secret_key_rejected(self, monkeypatch):
        """SECRET_KEY 为空时应拒绝启动"""
        from app.core.exceptions import SettingNotFound
        from app.__init__ import _validate_settings, settings

        monkeypatch.setattr(settings, "SECRET_KEY", "")
        with pytest.raises(SettingNotFound, match="SECRET_KEY"):
            _validate_settings()

    def test_valid_secret_key_passes(self, monkeypatch):
        """SECRET_KEY 有效时不应报错"""
        from app.__init__ import _validate_settings, settings

        monkeypatch.setattr(settings, "SECRET_KEY", "valid-key-32chars-long-enough!!")
        monkeypatch.setattr(settings, "DEBUG", True)
        _validate_settings()  # 不应抛异常

    def test_cors_star_rejected_in_production(self, monkeypatch):
        """P0: 生产环境下 CORS=["*"] 应拒绝启动"""
        from app.core.exceptions import SettingNotFound
        from app.__init__ import _validate_settings, settings

        monkeypatch.setattr(settings, "SECRET_KEY", "valid-key-32chars-long-enough!!")
        monkeypatch.setattr(settings, "DEBUG", False)
        monkeypatch.setattr(settings, "CORS_ORIGINS", ["*"])
        with pytest.raises(SettingNotFound, match="CORS_ORIGINS"):
            _validate_settings()

    def test_cors_localhost_rejected_in_production(self, monkeypatch):
        """P0: 生产环境下 CORS=["http://localhost"] 应拒绝启动"""
        from app.core.exceptions import SettingNotFound
        from app.__init__ import _validate_settings, settings

        monkeypatch.setattr(settings, "SECRET_KEY", "valid-key-32chars-long-enough!!")
        monkeypatch.setattr(settings, "DEBUG", False)
        monkeypatch.setattr(settings, "CORS_ORIGINS", ["http://localhost"])
        with pytest.raises(SettingNotFound, match="CORS_ORIGINS"):
            _validate_settings()

    def test_cors_star_allowed_in_debug(self, monkeypatch):
        """DEBUG 模式下 CORS=["*"] 不报错"""
        from app.__init__ import _validate_settings, settings

        monkeypatch.setattr(settings, "SECRET_KEY", "valid-key-32chars-long-enough!!")
        monkeypatch.setattr(settings, "DEBUG", True)
        monkeypatch.setattr(settings, "CORS_ORIGINS", ["*"])
        _validate_settings()  # 不应抛异常

    def test_custom_cors_ok_in_production(self, monkeypatch):
        """生产环境指定具体域名不报错"""
        from app.__init__ import _validate_settings, settings

        monkeypatch.setattr(settings, "SECRET_KEY", "valid-key-32chars-long-enough!!")
        monkeypatch.setattr(settings, "DEBUG", False)
        monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://example.com"])
        _validate_settings()  # 不应抛异常
