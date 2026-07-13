"""
系统初始化脚本 —— 独立于应用启动执行的一次性数据初始化。

用法:
    python scripts/init_system.py

等价于调用 init_data()：创建超级用户、菜单、默认配置、Provider、同步 API、初始化角色。
生产环境部署流程：
    1. python scripts/init_system.py    # 首次部署执行
    2. uvicorn app:app ...              # 启动应用（不再执行数据初始化）
"""
import asyncio
import sys
import os
import traceback

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.init_app import init_data


async def main():
    print(">>> 开始系统初始化...")
    try:
        await init_data()
        print(">>> 系统初始化完成")
    except Exception as e:
        print(f">>> 初始化失败: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
