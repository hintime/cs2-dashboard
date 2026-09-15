@echo off
REM ============================================================
REM  CS2 看板 · 本机更新调度器 —— 停止脚本
REM ============================================================
chcp 65001 >nul
setlocal
set "REPO=%~dp0"

echo ============================================================
echo   停止 CS2 本机更新调度器
echo ============================================================

if not exist "%REPO%.updater.lock" (
    echo [提示] 没有锁文件，调度器似乎未在运行。
) else (
    set /p OLDPID=<"%REPO%.updater.lock"
    echo   发现 PID=%OLDPID%，正在结束...
    taskkill /PID %OLDPID% /F >nul 2>&1
    if errorlevel 1 (
        echo   [警告] 结束进程失败，可能已退出。
    ) else (
        echo   [OK] 已结束 PID=%OLDPID%
    )
    del /f /q "%REPO%.updater.lock" >nul 2>&1
)

echo.
echo   移除开机自启...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" ^
    /v "CS2DashboardUpdater" /f >nul 2>&1
if errorlevel 1 (
    echo   [提示] 自启项不存在或已移除
) else (
    echo   [OK] 已移除自启项
)

echo.
echo   完成。
pause
