@echo off
chcp 65001 >nul
cd /d "%~dp0"
python netease_dl.py
pause
