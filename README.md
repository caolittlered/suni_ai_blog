# Suni AI Blog

企业知识智能体平台 - 让企业知识活起来。

## 🌟 功能特性

- **智能问答**: 基于企业内部知识库的自然语言问答
- **知识库管理**: 上传文档自动构建向量索引
- **用户隔离**: 每个用户独立的知识空间和会话
- **RAG 增强**: 结合语义检索与重排序，精准回答

## 🛠️ 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | FastAPI |
| 前端 | HTML/CSS/JS (简洁) |
| 数据库 | SQLite + SQLAlchemy |
| AI 后端 | OpenClaw Gateway |
| Embedding | BAAI/bge-large-zh-v1.5 |
| Reranker | BAAI/bge-reranker-large |
| 向量数据库 | ChromaDB |

## 🚀 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/your-username/suni_ai_blog.git
cd suni_ai_blog
```

### 2. 启动服务

**Windows:**
```powershell
.\start.bat
```

**Linux/Mac:**
```bash
chmod +x start.sh
./start.sh
```

### 3. 配置

编辑 `.env` 文件：
```env
JWT_SECRET=your-secret-key
OPENCLAW_GATEWAY_TOKEN=your-token
ALIYUN_API_KEY=your-api-key
```

### 4. 访问

打开浏览器访问 http://localhost:3000

## 📁 项目结构

```
suni_ai_blog/
├── app/
│   ├── static/          # 静态文件 (CSS/JS)
│   ├── templates/       # HTML 模板
│   ├── models.py        # 数据库模型
│   ├── auth.py          # 认证模块
│   ├── openclaw_client.py  # OpenClaw 客户端
│   ├── rag_engine.py    # RAG 引擎
│   └── document_processor.py  # 文档处理
├── data/                # 数据目录
│   ├── knowledge/       # 上传的知识文档
│   └── chroma/          # 向量数据库
├── config.yaml          # 配置文件
├── main.py              # 主应用
└── requirements.txt     # Python 依赖
```

## 🔧 API 接口

### 认证

- `POST /api/register` - 用户注册
- `POST /api/login` - 用户登录
- `GET /api/me` - 获取当前用户信息

### 聊天

- `POST /api/chat` - 发送消息
- `POST /api/chat/stream` - 流式对话 (SSE)

### 知识库

- `POST /api/knowledge/upload` - 上传文档
- `GET /api/knowledge/documents` - 列出文档
- `DELETE /api/knowledge/documents/{id}` - 删除文档

## 📝 开发说明

### 前置条件

1. **OpenClaw Gateway** 需要先启动
   ```bash
   openclaw gateway start
   ```

2. **模型下载** (首次运行需要下载 BGE 模型)
   ```bash
   # 国内用户
   export HF_ENDPOINT=https://hf-mirror.com
   ```

### 本地开发

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
.\venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
uvicorn main:app --reload --port 3000
```

## 🌐 部署

### VPS 部署

1. 安装依赖
2. 配置 Nginx 反向代理
3. 使用 systemd 管理服务

```ini
# /etc/systemd/system/suni.service
[Unit]
Description=Suni AI Blog
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/suni_ai_blog
ExecStart=/path/to/venv/bin/uvicorn main:app --host 0.0.0.0 --port 3000
Restart=always

[Install]
WantedBy=multi-user.target
```

### Docker 部署 (待完善)

```bash
docker build -t suni-ai .
docker run -p 3000:3000 suni-ai
```

## 📄 License

MIT License