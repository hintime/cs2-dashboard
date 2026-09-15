@echo off
REM ============================================================
REM  CS2 看板 · 本机更新调度器 —— 安装（Windows 计划任务版）
REM
REM  相比注册表 Run 项，计划任务的优点：
REM    · 以当前用户身份运行（不触发 git 的 dubious-ownership 防护）
REM    · 可在「未登录」时也运行 / 登录后延迟启动
REM    · 进程意外退出后有计划任务级的重启
REM    · 错过的时间点可在唤醒后补跑
REM
REM  两个任务：
REM    CS2-Updater-AtLogon   登录后延迟 1 分钟启动常驻调度器
REM    CS2-Updater-Watchdog  每 15 分钟巡检，进程不在则拉起
REM ============================================================
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "TASK1=CS2-Updater-AtLogon"
set "TASK2=CS2-Updater-Watchdog"

REM ── 定位仓库目录：优先本脚本所在目录，其次标准 runner 工作目录 ──
set "REPO=%~dp0"
if not exist "%REPO%update.py" (
    set "REPO=C:\actions-runner\_work\cs2-dashboard\cs2-dashboard\"
)
if not exist "%REPO%updater_daemon.py" (
    echo [错误] 在 %REPO% 找不到 updater_daemon.py
    echo        请把本脚本放到仓库根目录后再运行。
    pause & exit /b 1
)

REM ── 定位 pythonw.exe（无窗口）──
set "PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\pythonw.exe"
if not exist "%PY%" set "PY=pythonw.exe"

echo ============================================================
echo   CS2 看板 · 调度器安装（计划任务）
echo ============================================================
echo   仓库    : %REPO%
echo   解释器  : %PY%
echo.

REM ── 1. 登录后启动 ──
schtasks /Query /TN "%TASK1%" >nul 2>&1
if not errorlevel 1 (
    echo [%TASK1%] 已存在，先删除旧任务...
    schtasks /Delete /TN "%TASK1%" /F >nul 2>&1
)
schtasks /Create ^
    /TN "%TASK1%" ^
    /TR "\"%PY%\" \"%REPO%updater_daemon.py\"" ^
    /SC ONLOGON ^
    /DELAY 0001:00 ^
    /F >nul
if errorlevel 1 (
    echo   [警告] 创建 %TASK1% 失败
) else (
    echo   [OK] %TASK1%  : 登录后 1 分钟启动调度器
)

REM ── 2. 巡检看门狗 ──
schtasks /Query /TN "%TASK2%" >nul 2>&1
if not errorlevel 1 (
    echo [%TASK2%] 已存在，先删除旧任务...
    schtasks /Delete /TN "%TASK2%" /F >nul 2>&1
)
schtasks /Create ^
    /TN "%TASK2%" ^
    /TR "cmd /c \"\"%PY%\" \"%REPO%updater_daemon.py\" --watchdog\"" ^
    /SC MINUTE ^
    /MO 15 ^
    /F >nul
if errorlevel 1 (
    echo   [警告] 创建 %TASK2% 失败
) else (
    echo   [OK] %TASK2%  : 每 15 分钟巡检，掉线自动拉起
)

REM ── 3. 立即启动一次 ──
echo.
echo [3/3] 立即启动调度器...
start "" /B "%PY%" "%REPO%updater_daemon.py" >nul 2>&1
timeout /t 4 /nobreak >nul

echo.
echo ============================================================
echo   完成
echo   查看状态: "%PY% " 有窗口版请用 python.exe
echo     python "%REPO%updater_daemon.py" --status
echo   查看日志: %REPO%logs\
echo   卸载任务: uninstall_updater.bat
echo ============================================================
echo.
pause
