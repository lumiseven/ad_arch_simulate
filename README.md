# 互联网广告系统架构演示

这是一个用于理解现代程序化广告生态系统的架构演示项目，包含五个核心组件：

1. **广告管理平台 (Ad Management)** - 管理广告活动和预算
2. **需求方平台 (DSP)** - 代表广告主参与实时竞价
3. **供应方平台 (SSP)** - 管理媒体方广告位库存
4. **广告交易平台 (Ad Exchange)** - 促成DSP和SSP之间的实时竞价
5. **数据管理平台 (DMP)** - 管理用户画像和行为数据

## 架构

系统采用微服务架构，每个组件都作为独立的FastAPI服务运行，通过RESTful API进行通信。

## 项目结构

```text
ad-system-architecture/
├── pyproject.toml              # 项目配置和依赖管理
├── server/                     # 服务实现
│   ├── ad-management/          # 广告管理平台服务
│   ├── dsp/                    # 需求方平台服务
│   ├── ssp/                    # 供应方平台服务
│   ├── ad-exchange/            # 广告交易平台服务
│   └── dmp/                    # 数据管理平台服务
├── shared/                     # 共享模块和工具
│   ├── models.py              # Pydantic数据模型
│   └── utils.py               # 通用工具和辅助函数
├── tests/                     # 测试套件
├── scripts/                   # 实用脚本
│   └── start_services.py      # 启动所有服务的脚本
└── docs/                      # 文档
```

## 快速开始

1. 安装依赖: `uv sync`
2. 启动所有服务: `python scripts/start_services.py`
3. 访问各服务的 `/docs` 端点查看API文档

## 服务地址

- 广告管理平台: http://127.0.0.1:8001
- 需求方平台 (DSP): http://127.0.0.1:8002  
- 供应方平台 (SSP): http://127.0.0.1:8003
- 广告交易平台: http://127.0.0.1:8004
- 数据管理平台 (DMP): http://127.0.0.1:8005

## 开发说明

每个服务都使用FastAPI构建，包含：
- 健康检查端点
- 自动API文档生成
- 通过Pydantic共享数据模型
- 结构化日志记录
- 服务间通信工具
