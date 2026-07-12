"""PyInstaller 打包入口

通过 importlib 直接加载 hubstudio_agent 模块，
绕过 app/__init__.py，避免将 FastAPI 等服务端重依赖打进 EXE。

构建命令:
    pyinstaller hubstudio_agent.spec
"""

import importlib.util
import os
import sys


def _find_module(relative_path):
    """在 PyInstaller frozen 和开发模式下均能定位文件"""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        # 入口在 agent_build/ 子目录，需要回到项目根目录
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.normpath(os.path.join(base, relative_path))


def main():
    # 确保当前目录在 sys.path 中（frozen 模式下 .env 等相对路径依赖）
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        os.chdir(exe_dir)
        sys.path.insert(0, exe_dir)

    agent_path = _find_module(os.path.join("app", "agent", "hubstudio_agent.py"))
    spec = importlib.util.spec_from_file_location(
        "hubstudio_agent", agent_path, submodule_search_locations=[]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 Agent: {agent_path}")

    agent_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent_module)
    agent_module.main()


if __name__ == "__main__":
    main()
