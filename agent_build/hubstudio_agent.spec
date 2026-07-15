# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for HubStudioAgent 单文件打包

构建:
    pyinstaller hubstudio_agent.spec

输出:
    dist/HubStudioAgent.exe
"""

from PyInstaller.utils.hooks import collect_submodules

# 自动收集 DrissionPage 所有子模块（PyInstaller 不会追踪懒导入）
drission_hidden = collect_submodules("DrissionPage")

a = Analysis(
    ["build_agent_entry.py"],
    pathex=[".."],
    binaries=[],
    datas=[
        # 默认 .env 配置（用户可在 EXE 同目录放 .env 覆盖）
        (".env", "."),
        # Agent 入口模块（通过 importlib 直接加载，绕过 app/__init__.py）
        ("../app/agent/hubstudio_agent.py", "app/agent"),
        # executor 适配层 + 拆分后的子模块
        ("../app/services/hubstudio_executor.py", "app/services"),
        ("../app/services/hubstudio/__init__.py", "app/services/hubstudio"),
        ("../app/services/hubstudio/client.py", "app/services/hubstudio"),
        ("../app/services/hubstudio/logger.py", "app/services/hubstudio"),
        ("../app/services/hubstudio/runtime.py", "app/services/hubstudio"),
        ("../app/services/hubstudio/executor.py", "app/services/hubstudio"),
        ("../app/services/hubstudio/tasks/__init__.py", "app/services/hubstudio/tasks"),
        ("../app/services/hubstudio/tasks/create_env.py", "app/services/hubstudio/tasks"),
        ("../app/services/hubstudio/tasks/create_account.py", "app/services/hubstudio/tasks"),
        ("../app/services/hubstudio/tasks/update_env.py", "app/services/hubstudio/tasks"),
        ("../app/services/hubstudio/tasks/wp_login.py", "app/services/hubstudio/tasks"),
        ("../app/services/hubstudio/tasks/gmc_check.py", "app/services/hubstudio/tasks"),
    ],
    hiddenimports=[
        # Agent 核心依赖
        "app.agent.hubstudio_agent",
        "app.agent",
        # executor 依赖
        "requests",
        "urllib3",
        "charset_normalizer",
        "certifi",
        "idna",
        # 可选依赖（try/except 导入，PyInstaller 不会自动追踪）
        "dotenv",
        # 浏览器自动化（wp_login / gmc_check 任务需要）
        *drission_hidden,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除服务端重型依赖（Agent 不需要）
        "fastapi",
        "starlette",
        "uvicorn",
        "tortoise",
        "tortoise_orm",
        "aerich",
        "pypika_tortoise",
        "aiosqlite",
        "pydantic",
        "pydantic_core",
        "pydantic_settings",
        "passlib",
        "argon2",
        "email_validator",
        "jinja2",
        "jinja2.ext",
        "markupsafe",
        "orjson",
        "ujson",
        "pyjwt",
        "typer",
        "rich",
        "watchfiles",
        "websockets",
        "httpx",
        "httpcore",
        "httptools",
        "uvloop",
        "python_multipart",
        "dnspython",
        "iso8601",
        "pytz",
        "loguru",
        "sniffio",
        "anyio",
        "h11",
        "asyncclick",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HubStudioAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 显示控制台窗口（查看日志）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可选：指定 .ico 图标路径
)
