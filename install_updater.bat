@echo off
REM ============================================================
REM  CS2 看板 · 本机更新调度器 —— 安装/启动脚本
REM  以「后台无窗口」方式启动 updater_daemon.py，并设置开机自启
REM ============================================================
chcp 65001 >nul
setlocal

set "REPO=%~dp0"
set "PYTHON=C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

echo ============================================================
echo   CS2 看板 · 本机更新调度器 安装
echo ============================================================
echo   仓库 : %REPO%
echo   解释器: %PYTHON%
echo.

REM ── 1. 检查脚本存在 ──
if not exist "%REPO%updater_daemon.py" (
    echo [错误] 找不到 updater_daemon.py
    pause
    exit /b 1
)

REM ── 2. 检查是否已在运行 ──
if exist "%REPO%.updater.lock" (
    set /p OLDPID=<"%REPO%.updater.lock"
    echo [提示] 检测到锁文件 PID=%OLDPID%，可能已在运行。
    echo        如需重启，请先运行 stop_updater.bat
    echo.
)

echo [1/3] 创建一个隐藏窗口的运行器...
REM 用 pythonw.exe 启动，完全不弹窗
set "PYW=%PYTHON:python.exe=pythonw.exe%"
if not exist "%PYW%" set "PYW=%PYTHON%"

echo [2/3] 启动调度器（后台）...
if exist "%PYW%" (
    start "" /B "%PYW%" "%REPO%updater_daemon.py" >nul 2>&1
) else (
    start "" /MIN "%PYTHON%" "%REPO%updater_daemon.py"
)
timeout /t 3 /nobreak >nul

echo [3/3] 设置开机自启（注册表 Run 项）...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" ^
    /v "CS2DashboardUpdater" ^
    /t REG_SZ ^
    /d "\"%PYW%\" \"%REPO%updater_daemon.py\"" ^
    /f >nul
if errorlevel 1 (
    echo   [警告] 写入自启项失败
) else (
    echo   [OK] 已加入开机自启: CS2DashboardUpdater
)

echo.
echo ============================================================
echo   完成！
echo   调度器已在后台运行，每 30 分钟更新价格，每 6 小时全量更新。
echo   查看状态: python updater_daemon.py --status
echo   查看日志: %REPO%logs\
echo   停止运行: 运行 stop_updater.bat
echo ============================================================
echo.
pause
