@echo off
REM ============================================================
REM  CS2 看板 · 本机更新调度器 —— 卸载 / 停止
REM  1) 删除计划任务（AtLogon + Watchdog）
REM  2) 删除注册表 Run 项（若曾用旧版 install_updater.bat 装过）
REM  3) 结束正在运行的调度器进程
REM ============================================================
chcp 65001 >nul
setlocal

set "TASK1=CS2-Updater-AtLogon"
set "TASK2=CS2-Updater-Watchdog"
set "REPO=%~dp0"
if not exist "%REPO%update.py" set "REPO=C:\actions-runner\_work\cs2-dashboard\cs2-dashboard\"

echo ============================================================
echo   CS2 看板 · 调度器卸载
echo ============================================================
echo.

echo [1/3] 删除计划任务...
schtasks /Delete /TN "%TASK1%" /F >nul 2>&1
if errorlevel 1 (echo   - %TASK1% 不存在或删除失败) else (echo   [OK] 已删除 %TASK1%)
schtasks /Delete /TN "%TASK2%" /F >nul 2>&1
if errorlevel 1 (echo   - %TASK2% 不存在或删除失败) else (echo   [OK] 已删除 %TASK2%)

echo [2/3] 清理注册表自启项...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "CS2DashboardUpdater" /f >nul 2>&1
if errorlevel 1 (echo   - 无该自启项) else (echo   [OK] 已移除自启项)

echo [3/3] 停止运行中的调度器...
if exist "%REPO%.updater.lock" (
    set /p OLDPID=<"%REPO%.updater.lock"
    taskkill /PID !OLDPID! /F >nul 2>&1
    if errorlevel 1 (echo   - PID !OLDPID! 未在运行) else (echo   [OK] 已结束 PID !OLDPID!)
    del /f /q "%REPO%.updater.lock" >nul 2>&1
) else (
    echo   - 无锁文件，可能本就未运行
)
REM 兜底：按命令行特征清理
wmic process where "name like 'python%%' and commandline like '%%updater_daemon.py%%'" delete >nul 2>&1

echo.
echo ============================================================
echo   卸载完成。数据与日志均未删除：
echo     日志: %REPO%logs\
echo     状态: %REPO%.updater_state.json
echo ============================================================
echo.
pause
