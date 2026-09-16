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
REM  两个机制（互补）：
REM    HKCU Run 项               登录后启动常驻调度器（无需任何特权）
REM    CS2-Updater-Watchdog      每 15 分钟巡检，进程不在则拉起（/SC MINUTE 普通权限即可）
REM
REM  ⚠️ 2026-09-16 修订一：原先用 CS2-Updater-AtLogon(/SC ONLOGON) 做登录自启，
REM     但该触发器**需要管理员权限**，普通双击必报「拒绝访问」→ 任务静默建不出来。
REM     已改为写 HKCU\...\Run 项，效果等价且免提权。
REM
REM  ⚠️ 2026-09-16 修订二：★ 一切自启/任务都必须满足「静默、不弹窗」：
REM     · 用 **pythonw.exe**（GUI 子系统，无控制台），不要用 python.exe
REM     · **绝不要包 `cmd /c`** —— cmd.exe 是控制台程序，任务每跑一次就弹一次黑窗
REM     · 不要用 `start ""` 不带 /B（会新建窗口）
REM     这三条任一违反，用户就会每 15 分钟被弹一次窗口。
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

REM ── 1. 登录自启 ──
REM ⚠️ 2026-09-16 修订：**不再用 `/SC ONLOGON`**。
REM    原因：创建 ONLOGON 触发器需要管理员权限，普通双击运行必报「拒绝访问」，
REM    于是任务静默建不出来（就是"双击了却没反应"的元凶之一）。
REM    改用 HKCU\...\Run 注册表项 —— 效果等价（登录后启动），且**无需任何特权**。
echo [1/3] 写入登录自启项（HKCU Run，无需管理员权限）...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" ^
    /v "CS2DashboardUpdater" ^
    /t REG_SZ ^
    /d "\"%PY%\" \"%REPO%updater_daemon.py\"" /f >nul
if errorlevel 1 (
    echo   [警告] 写入 Run 项失败
) else (
    echo   [OK] 已写入 Run 项 CS2DashboardUpdater（登录后自启）
)

REM ── 2. 巡检看门狗 ──
REM ⚠️ 2026-09-16 修订：**不要用 `cmd /c` 包一层**。
REM    原因：cmd.exe 是控制台程序 —— 任务每 15 分钟运行一次，
REM    就会弹出一次黑窗口。而 pythonw.exe 属于 GUI 子系统，
REM    直接调用**不会创建任何控制台窗口**。
REM    （原先写 `cmd /c` 只是为了绕引号转义，但代价是每 15 分钟弹一次窗。）
schtasks /Query /TN "%TASK2%" >nul 2>&1
if not errorlevel 1 (
    echo [%TASK2%] 已存在，先删除旧任务...
    schtasks /Delete /TN "%TASK2%" /F >nul 2>&1
)
schtasks /Create ^
    /TN "%TASK2%" ^
    /TR "\"%PY%\" \"%REPO%updater_daemon.py\" --watchdog" ^
    /SC MINUTE ^
    /MO 15 ^
    /F >nul
if errorlevel 1 (
    echo   [警告] 创建 %TASK2% 失败
) else (
    echo   [OK] %TASK2%  : 每 15 分钟巡检，掉线自动拉起（静默，无窗口）
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
