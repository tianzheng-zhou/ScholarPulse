#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -f ".venv/bin/python" ]; then
    echo "[!] 未找到虚拟环境，正在创建..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

if [ ! -f ".env" ]; then
    echo "[!] 未找到 .env 文件，正在从模板创建..."
    cp .env.example .env
    echo "[!] 请编辑 .env 文件填入 DASHSCOPE_API_KEY 后重新运行"
    exit 1
fi

echo ""
echo " ============================================"
echo "  ScholarPulse - 多平台聚合学术 AI 日报系统"
echo " ============================================"
echo "  访问地址: http://127.0.0.1:15471"
echo " ============================================"
echo ""

python -m uvicorn scholarpulse.main:app --host 127.0.0.1 --port 15471 --reload
