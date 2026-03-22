#!/bin/bash
echo "================================"
echo "Suni AI Blog - 启动脚本"
echo "================================"
echo

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python，请先安装 Python 3.10+"
    exit 1
fi

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "[信息] 创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "[信息] 检查依赖..."
pip install -r requirements.txt -q

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "[信息] 复制环境变量模板..."
    cp .env.example .env
    echo "[提示] 请编辑 .env 文件配置您的密钥"
fi

# 启动服务
echo
echo "[信息] 启动 Suni AI 服务..."
echo "[信息] 访问地址: http://localhost:3000"
echo
python main.py