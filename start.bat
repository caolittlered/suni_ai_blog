@echo off
echo ================================
echo Suni AI Blog - 启动脚本
echo ================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM 检查虚拟环境
if not exist "venv" (
    echo [信息] 创建虚拟环境...
    python -m venv venv
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 安装依赖
echo [信息] 检查依赖...
pip install -r requirements.txt -q

REM 检查 .env 文件
if not exist ".env" (
    echo [信息] 复制环境变量模板...
    copy .env.example .env
    echo [提示] 请编辑 .env 文件配置您的密钥
)

REM 启动服务
echo.
echo [信息] 启动 Suni AI 服务...
echo [信息] 访问地址: http://localhost:3000
echo.
python main.py