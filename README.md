# proxy_pool

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![License MIT](https://img.shields.io/badge/license-MIT-green.svg)
![Docker](https://img.shields.io/badge/docker-ready-blue.svg)

**SMTP 邮件系统代理IP池管理模块**——支持 HTTP/SOCKS5、健康检测、Web UI、Docker 化。

一个轻量级、高可用的代理IP池管理组件，专为需要稳定代理服务的应用设计（如邮件发送、数据采集、API调用等）。提供 RESTful API 和现代化 Web 管理界面。

## ✨ Features

- **多协议支持**: HTTP/HTTPS、SOCKS4/SOCKS5 代理协议，支持认证
- **智能健康检测**: 异步并发检测，实时状态更新，自动剔除失效代理
- **Web 管理界面**: 现代暗色主题，实时监控，手动管理操作
- **RESTful API**: 完整的 CRUD 接口，支持批量操作与实时统计
- **Docker 容器化**: 一键部署，支持环境变量配置
- **配置驱动**: JSON/YAML 配置，热重载，运行时调整
- **高性能池化**: 基于内存的高效代理池，支持轮询/随机调度
- **扩展性架构**: 插件式设计，支持自定义代理源与检测策略

## 🚀 Quick Start

### 本地运行

1. **克隆项目**:
   ```bash
   git clone https://github.com/yourname/proxy_pool.git
   cd proxy_pool
   ```

2. **安装依赖**:
   ```bash
   pip install -r requirements.txt
   ```

3. **启动 Web UI**:
   ```bash
   python web_ui.py --host 0.0.0.0 --port 5000
   ```
   访问 http://localhost:5000 进入管理界面。

### Docker 运行

```bash
# 构建镜像
docker build -t proxy_pool .

# 运行容器
docker run -d -p 5000:5000 --name proxy_pool proxy_pool

# 使用自定义配置
docker run -d -p 5000:5000 \
  -v $(pwd)/config:/app/config \
  -e LOG_LEVEL=DEBUG \
  proxy_pool
```

## 📁 目录结构

```
proxy_pool/
├── Dockerfile                  # Docker 构建文件
├── .dockerignore              # Docker 忽略文件
├── requirements.txt           # Python 依赖
├── README.md                  # 本文档
├── LICENSE                    # MIT 许可证
├── __init__.py               # 包初始化
├── config.py                 # 配置管理
├── models.py                 # 数据模型（ProxyEntry, PoolConfig等）
├── pool.py                   # 代理池核心逻辑
├── health.py                 # 健康检测模块
├── connector.py              # 代理连接器
├── fetcher.py                # 代理源抓取
├── web_ui.py                 # Flask Web UI 主程序
└── tests/                    # 测试套件
    ├── test_models.py
    ├── test_pool.py
    ├── test_health.py
    ├── test_integration.py
    └── smoke_test.py
```

## 🔌 API 文档

### REST 端点

| 方法 | 路径 | 描述 |
|------|------|------|
| `GET` | `/` | Web UI 主页面（单页应用） |
| `GET` | `/api/stats` | 获取代理池统计信息（总数、存活数、死亡率等） |
| `GET` | `/api/proxies` | 获取所有代理列表，支持 `?status=alive/dead/untested` 过滤 |
| `POST` | `/api/proxies` | 批量添加代理，JSON 格式：`{"proxies": ["http://user:pass@host:port", "socks5://host:port"]}` |
| `DELETE` | `/api/proxies/<id>` | 删除指定ID的代理 |
| `POST` | `/api/proxies/<id>/check` | 立即检测单个代理，返回实时状态 |
| `POST` | `/api/proxies/<id>/mark_dead` | 手动标记代理为死亡 |
| `POST` | `/api/proxies/<id>/mark_alive` | 手动标记代理为存活（恢复） |
| `GET` | `/api/config` | 获取当前配置（健康检测间隔、调度模式等） |
| `POST` | `/api/config` | 更新配置（部分或全部） |
| `POST` | `/api/check_all` | 触发全量健康检测 |
| `GET` | `/api/export` | 导出所有代理为纯文本列表（每行一个代理） |

### 示例请求

```bash
# 获取统计
curl http://localhost:5000/api/stats

# 添加代理
curl -X POST http://localhost:5000/api/proxies \
  -H "Content-Type: application/json" \
  -d '{"proxies": ["http://proxy1.com:8080", "socks5://user:pass@proxy2.com:1080"]}'

# 导出代理列表
curl http://localhost:5000/api/export > proxies.txt
```

## 📸 Web UI 截图

*TODO: 添加 Web UI 截图*

## 🧪 测试

项目包含完整的单元测试与集成测试。

```bash
# 安装测试依赖
pip install pytest pytest-asyncio

# 运行所有测试
pytest -v

# 运行特定测试模块
pytest tests/test_pool.py -v

# 生成覆盖率报告
pytest --cov=proxy_pool --cov-report=html
```

## 📄 License

本项目采用 **MIT 许可证**。详见 [LICENSE](LICENSE) 文件。

Copyright © 2026 RayKim