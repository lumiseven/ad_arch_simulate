# 部署和运行文档

## 概述

本文档描述了如何部署和运行互联网广告系统架构演示项目。系统支持多种部署方式，包括本地开发、Docker容器化部署和生产环境部署。

## 系统要求

### 最低要求
- Python 3.9+
- 内存: 2GB RAM
- 磁盘空间: 1GB
- 网络: 开放端口 8001-8005

### 推荐配置
- Python 3.11+
- 内存: 4GB RAM
- 磁盘空间: 5GB
- CPU: 2核心以上

## 部署方式

### 1. 本地开发部署

#### 安装依赖
```bash
# 安装 uv (Python 包管理器)
pip install uv

# 克隆项目
git clone <repository-url>
cd ad-system-architecture

# 安装项目依赖
uv sync
```

#### 初始化数据库
```bash
# 初始化数据库
python scripts/init_database.py

# 验证数据库连接
python -c "from shared.database import check_database_health; import asyncio; print(asyncio.run(check_database_health()))"
```

#### 启动服务
```bash
# 启动所有服务
python scripts/start_services.py

# 或者单独启动服务
python -m server.ad-management.main &
python -m server.dsp.main &
python -m server.ssp.main &
python -m server.ad-exchange.main &
python -m server.dmp.main &
```

### 2. Docker 容器化部署

#### 构建镜像
```bash
# 构建开发镜像
docker build -t ad-system:dev --target development .

# 构建生产镜像
docker build -t ad-system:prod --target production .
```

#### 使用 Docker Compose (推荐)

##### 分离服务部署
```bash
# 启动所有服务 (每个服务独立容器)
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

##### 单容器部署
```bash
# 启动单容器模式 (所有服务在一个容器中)
docker-compose --profile all-in-one up -d ad-system-all

# 查看日志
docker-compose logs -f ad-system-all
```

#### 手动 Docker 运行
```bash
# 创建网络
docker network create ad-system-network

# 创建数据卷
docker volume create ad-system-data

# 运行容器
docker run -d \
  --name ad-system \
  --network ad-system-network \
  -p 8001:8001 -p 8002:8002 -p 8003:8003 -p 8004:8004 -p 8005:8005 \
  -v ad-system-data:/app/data \
  ad-system:dev
```

### 3. 生产环境部署

#### 环境配置
```bash
# 创建生产配置文件
cp config.example.json config.json

# 编辑配置文件
vim config.json
```

#### 使用 systemd 服务
```bash
# 创建服务文件
sudo tee /etc/systemd/system/ad-system.service > /dev/null <<EOF
[Unit]
Description=Ad System Architecture Demo
After=network.target

[Service]
Type=simple
User=app
WorkingDirectory=/opt/ad-system
ExecStart=/opt/ad-system/.venv/bin/python scripts/start_services.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 启用并启动服务
sudo systemctl enable ad-system
sudo systemctl start ad-system
sudo systemctl status ad-system
```

## 配置管理

### 环境变量配置
```bash
# 服务配置
export HOST=0.0.0.0
export DEBUG=false
export LOG_LEVEL=INFO

# 数据库配置
export DATABASE_URL=sqlite+aiosqlite:///./data/ad_system.db
export DATABASE_ECHO=false
export DATABASE_POOL_SIZE=5

# RTB 配置
export RTB_TIMEOUT_MS=100
export DSP_TIMEOUT_MS=50
```

### 配置文件示例
```json
{
  "service": {
    "host": "0.0.0.0",
    "debug": false
  },
  "database": {
    "url": "sqlite+aiosqlite:///./data/ad_system.db",
    "echo": false,
    "pool_size": 5
  },
  "rtb": {
    "timeout_ms": 100,
    "dsp_timeout_ms": 50
  },
  "logging": {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  }
}
```

## 服务端口和访问

### 服务端口映射
- **广告管理平台**: http://localhost:8001
- **需求方平台 (DSP)**: http://localhost:8002
- **供应方平台 (SSP)**: http://localhost:8003
- **广告交易平台**: http://localhost:8004
- **数据管理平台 (DMP)**: http://localhost:8005

### API 文档访问
每个服务都提供 Swagger UI 文档：
- 广告管理平台: http://localhost:8001/docs
- DSP: http://localhost:8002/docs
- SSP: http://localhost:8003/docs
- 广告交易平台: http://localhost:8004/docs
- DMP: http://localhost:8005/docs

### 健康检查端点
所有服务都提供健康检查端点：
- GET `/health` - 基本健康检查
- GET `/health/detailed` - 详细健康信息

## 监控和日志

### 日志配置
```bash
# 日志目录结构
logs/
├── ad-management.log
├── dsp.log
├── ssp.log
├── ad-exchange.log
├── dmp.log
└── system.log
```

### 监控指标
系统提供以下监控指标：
- 服务健康状态
- 响应时间统计
- 错误率统计
- RTB 流程性能指标
- 数据库连接状态

### 查看监控信息
```bash
# 查看系统状态
curl http://localhost:8004/demo/workflow-stats

# 查看服务健康状态
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8004/health
curl http://localhost:8005/health
```

## 故障排除

### 常见问题

#### 1. 端口冲突
```bash
# 检查端口占用
netstat -tulpn | grep :800

# 修改端口配置
export PORT=9001  # 或修改配置文件
```

#### 2. 数据库连接失败
```bash
# 检查数据库文件权限
ls -la ad_system.db*

# 重新初始化数据库
rm -f ad_system.db*
python scripts/init_database.py
```

#### 3. 服务启动失败
```bash
# 查看详细错误日志
python scripts/start_services.py --debug

# 检查依赖安装
uv sync --frozen
```

#### 4. Docker 部署问题
```bash
# 查看容器日志
docker-compose logs service-name

# 重新构建镜像
docker-compose build --no-cache

# 清理并重启
docker-compose down -v
docker-compose up -d
```

### 性能调优

#### 数据库优化
```bash
# 增加数据库连接池大小
export DATABASE_POOL_SIZE=10

# 启用数据库连接复用
export DATABASE_POOL_RECYCLE=3600
```

#### 服务优化
```bash
# 调整 RTB 超时时间
export RTB_TIMEOUT_MS=150
export DSP_TIMEOUT_MS=75

# 启用请求缓存
export ENABLE_CACHE=true
export CACHE_TTL=300
```

## 安全配置

### 基本安全措施
1. 更改默认端口
2. 配置防火墙规则
3. 使用 HTTPS (生产环境)
4. 定期更新依赖包

### 生产环境安全
```bash
# 创建专用用户
sudo useradd -r -s /bin/false ad-system

# 设置文件权限
sudo chown -R ad-system:ad-system /opt/ad-system
sudo chmod 750 /opt/ad-system

# 配置防火墙
sudo ufw allow 8001:8005/tcp
sudo ufw enable
```

## 备份和恢复

### 数据备份
```bash
# 备份数据库
cp ad_system.db ad_system.db.backup.$(date +%Y%m%d_%H%M%S)

# 备份配置文件
tar -czf config_backup_$(date +%Y%m%d).tar.gz config.json .env
```

### 数据恢复
```bash
# 恢复数据库
cp ad_system.db.backup.20240101_120000 ad_system.db

# 重启服务
sudo systemctl restart ad-system
```

## 扩展和定制

### 添加新服务
1. 在 `server/` 目录下创建新服务目录
2. 实现 FastAPI 应用
3. 更新 `scripts/start_services.py`
4. 更新 Docker 配置

### 修改配置
1. 编辑 `shared/config.py`
2. 更新配置文件模板
3. 重新部署服务

## 支持和维护

### 日常维护
- 定期检查日志文件大小
- 监控系统资源使用情况
- 更新依赖包版本
- 备份重要数据

### 获取帮助
- 查看项目文档
- 检查 GitHub Issues
- 联系开发团队