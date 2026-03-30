@echo off
chcp 65001 >nul
title ScholarPulse

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] 未找到虚拟环境，正在创建...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

if not exist ".env" (
    echo [!] 未找到 .env 文件，正在从模板创建...
    copy .env.example .env
    echo [!] 请编辑 .env 文件填入 DASHSCOPE_API_KEY 后重新运行
    pause
    exit /b 1
)

echo.
echo  ============================================
echo   ScholarPulse - 多平台聚合学术 AI 日报系统
echo  ============================================
echo   访问地址: http://127.0.0.1:15471
echo  ============================================
echo.

python -m uvicorn scholarpulse.main:app --host 127.0.0.1 --port 15471 --reload
pause
