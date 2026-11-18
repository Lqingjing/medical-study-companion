@echo off
REM 公开展示版：已移除原作者本机的 Python 绝对路径，仅保留通用启动方式。
cd /d "%~dp0"
python launch.py %*
