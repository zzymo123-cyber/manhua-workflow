@echo off
chcp 65001 >nul
title Manhua Workflow

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-windows.ps1"
pause
