@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   HubStudioAgent EXE 打包脚本
echo ============================================
echo.

REM 回到项目根目录
cd /d "%~dp0.."

REM 检查 PyInstaller
python -m PyInstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [信息] 正在安装 PyInstaller...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [错误] PyInstaller 安装失败，请手动执行: pip install pyinstaller
        pause
        exit /b 1
    )
)

echo [1/2] 清理旧的构建产物...
REM 清理 agent_build 下的产物
if exist "agent_build\build" rmdir /s /q "agent_build\build"
if exist "agent_build\dist" rmdir /s /q "agent_build\dist"
REM 清理项目根目录的旧产物（之前版本可能留在根目录）
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo [2/2] 开始打包...
python -m PyInstaller ^
    --distpath agent_build\dist ^
    --workpath agent_build\build ^
    agent_build\hubstudio_agent.spec
if %errorlevel% neq 0 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo ============================================
echo   打包完成！
echo   输出文件: agent_build\dist\HubStudioAgent.exe
echo   文件大小:
dir "agent_build\dist\HubStudioAgent.exe" 2>nul
echo ============================================
echo.
echo 目录结构:
echo   agent_build\
echo     build_agent.bat          打包脚本
echo     build_agent_entry.py     入口文件
echo     hubstudio_agent.spec     打包配置
echo     build\                   PyInstaller 构建缓存
echo     dist\HubStudioAgent.exe  最终 EXE
echo.
echo 使用说明:
echo   1. 将 HubStudioAgent.exe 复制到目标 Windows 机器
echo   2. （可选）在同目录创建 .env 文件配置参数
echo   3. 双击运行或在命令行执行
echo.
echo 环境变量参考（也可写入同目录的 .env 文件）:
echo   HUB_AGENT_SERVER_URL   后端地址（默认 http://127.0.0.1:9999/api/v1）
echo   HUB_AGENT_USERNAME     登录账号
echo   HUB_AGENT_PASSWORD     登录密码
echo   HUB_AGENT_WORKER_NAME  Worker 节点名称
echo   HUB_AGENT_POLL_INTERVAL  轮询间隔秒（默认 5）
echo   HUB_AGENT_PROVIDER_ID    供应商 ID
echo   HUB_CONNECTOR_DIR        Connector 安装目录
echo   HUB_EXE_NAME             Connector 可执行文件名
echo   HUB_HTTP_PORT            Connector 端口（默认 6873）
echo   HUB_AGENT_LOG_DIR        日志目录（默认 ./logs/hubstudio）
echo.

pause
