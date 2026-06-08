@echo off
chcp 65001 >nul
title 漫剧工作流

echo 正在停止旧实例...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8002 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo 启动服务器...
cd /d "%~dp0"
start "" "http://localhost:8002"
python main.py
pause
