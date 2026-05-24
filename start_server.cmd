@echo off
title CS2 Dashboard 本地服务器
echo 正在启动 CS2 Dashboard 本地服务器...
echo.
echo 访问地址: http://localhost:8765
echo 关闭命令: Ctrl+C
echo.
cd /d "C:\Users\Lenovo\WorkBuddy\Claw\cs2-dashboard"
python server.py
pause
