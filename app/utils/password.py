# passlib 在 Python 3.12+ / setuptools 69+ 中依赖已移除的 pkg_resources，这里做 shim
import sys
try:
    import pkg_resources
except ImportError:
    # 提供一个最小化的 pkg_resources shim 让 passlib 能正常加载
    class _FakePkgResources:
        class Requirement:
            def __init__(*a, **kw): pass
            def __contains__(self, *a): return True
        def require(self, *a, **kw): pass
        get_distribution = lambda *a, **kw: type('obj', (object,), {'version': '1.0.0'})()
    sys.modules['pkg_resources'] = _FakePkgResources()

from passlib import pwd
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def generate_password() -> str:
    return pwd.genword()
