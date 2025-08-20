# API 接口文档和使用示例

## 概述

本文档详细描述了互联网广告系统架构演示项目的所有 API 接口，包括请求格式、响应格式和使用示例。系统包含五个核心服务，每个服务都提供 RESTful API 接口。

## 通用规范

### 基础 URL
- 广告管理平台: `http://localhost:8001`
- 需求方平台 (DSP): `http://localhost:8002`
- 供应方平台 (SSP): `http://localhost:8003`
- 广告交易平台: `http://localhost:8004`
- 数据管理平台 (DMP): `http://localhost:8005`

### 通用响应格式
```json
{
  "status": "success|error",
  "data": {},
  "message": "描述信息",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### 错误响应格式
```json
{
  "error_code": "ERROR_CODE",
  "message": "错误描述",
  "details": {},
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### 通用状态码
- `200` - 成功
- `201` - 创建成功
- `400` - 请求参数错误
- `404` - 资源未找到
- `500` - 服务器内部错误
- `503` - 服务不可用

## 1. 广告管理平台 API

### 1.1 健康检查
```http
GET /health
```

**响应示例:**
```json
{
  "status": "healthy",
  "service": "ad-management",
  "timestamp": "2024-01-01T12:00:00Z",
  "details": {
    "uptime": "5m 30s",
    "database": "connected"
  }
}
```

### 1.2 创建广告活动
```http
POST /campaigns
Content-Type: application/json

{
  "name": "春季促销活动",
  "advertiser_id": "advertiser_001",
  "budget": 10000.0,
  "targeting": {
    "age_range": {"min_age": 18, "max_age": 35},
    "interests": ["technology", "shopping"],
    "locations": ["北京", "上海", "广州"]
  },
  "creative": {
    "title": "春季大促销",
    "description": "全场商品8折优惠",
    "image_url": "https://example.com/ad.jpg",
    "landing_url": "https://example.com/promotion"
  }
}
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "id": "camp_001",
    "name": "春季促销活动",
    "advertiser_id": "advertiser_001",
    "budget": 10000.0,
    "spent": 0.0,
    "targeting": {
      "age_range": {"min_age": 18, "max_age": 35},
      "interests": ["technology", "shopping"],
      "locations": ["北京", "上海", "广州"]
    },
    "creative": {
      "title": "春季大促销",
      "description": "全场商品8折优惠",
      "image_url": "https://example.com/ad.jpg",
      "landing_url": "https://example.com/promotion"
    },
    "status": "active",
    "created_at": "2024-01-01T12:00:00Z",
    "updated_at": "2024-01-01T12:00:00Z"
  }
}
```

### 1.3 获取广告活动详情
```http
GET /campaigns/{campaign_id}
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "id": "camp_001",
    "name": "春季促销活动",
    "advertiser_id": "advertiser_001",
    "budget": 10000.0,
    "spent": 1250.0,
    "status": "active",
    "created_at": "2024-01-01T12:00:00Z",
    "updated_at": "2024-01-01T12:30:00Z"
  }
}
```

### 1.4 更新广告活动
```http
PUT /campaigns/{campaign_id}
Content-Type: application/json

{
  "name": "春季促销活动 - 延期",
  "budget": 15000.0,
  "status": "active"
}
```

### 1.5 获取活动统计数据
```http
GET /campaigns/{campaign_id}/stats
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "campaign_id": "camp_001",
    "impressions": 50000,
    "clicks": 2500,
    "conversions": 125,
    "spend": 1250.0,
    "revenue": 2500.0,
    "ctr": 0.05,
    "conversion_rate": 0.05,
    "roas": 2.0,
    "period": {
      "start": "2024-01-01T00:00:00Z",
      "end": "2024-01-01T23:59:59Z"
    }
  }
}
```

## 2. 需求方平台 (DSP) API

### 2.1 健康检查
```http
GET /health
```

### 2.2 接收竞价请求
```http
POST /bid
Content-Type: application/json

{
  "id": "bid_req_001",
  "user_id": "user_001",
  "ad_slot": {
    "width": 728,
    "height": 90,
    "position": "top",
    "floor_price": 0.5
  },
  "device": {
    "type": "desktop",
    "os": "Windows",
    "browser": "Chrome"
  },
  "geo": {
    "country": "CN",
    "city": "北京",
    "region": "北京市"
  },
  "user_profile": {
    "interests": ["technology", "shopping"],
    "demographics": {"age": 28, "gender": "male"}
  }
}
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "request_id": "bid_req_001",
    "price": 0.75,
    "creative": {
      "title": "科技产品推荐",
      "description": "最新科技产品，限时优惠",
      "image_url": "https://example.com/tech-ad.jpg",
      "landing_url": "https://example.com/tech-products"
    },
    "campaign_id": "camp_001",
    "dsp_id": "dsp_001"
  }
}
```

### 2.3 获取关联广告活动
```http
GET /campaigns
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "campaigns": [
      {
        "id": "camp_001",
        "name": "春季促销活动",
        "budget": 10000.0,
        "remaining_budget": 8750.0,
        "status": "active"
      }
    ],
    "total": 1
  }
}
```

### 2.4 接收竞价成功通知
```http
POST /win-notice
Content-Type: application/json

{
  "auction_id": "auction_001",
  "campaign_id": "camp_001",
  "price": 0.65,
  "impression_id": "imp_001"
}
```

### 2.5 获取竞价统计数据
```http
GET /stats
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "total_bids": 10000,
    "won_bids": 1250,
    "win_rate": 0.125,
    "average_bid_price": 0.68,
    "average_win_price": 0.72,
    "total_spend": 900.0,
    "period": {
      "start": "2024-01-01T00:00:00Z",
      "end": "2024-01-01T23:59:59Z"
    }
  }
}
```

## 3. 供应方平台 (SSP) API

### 3.1 健康检查
```http
GET /health
```

### 3.2 处理广告请求
```http
POST /ad-request
Content-Type: application/json

{
  "slot_id": "slot_001",
  "publisher_id": "pub_001",
  "ad_slot": {
    "width": 728,
    "height": 90,
    "position": "top",
    "floor_price": 0.3
  },
  "user_context": {
    "user_id": "user_001",
    "device_type": "desktop",
    "location": {"country": "CN", "city": "北京"}
  }
}
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "ad_content": {
      "title": "科技产品推荐",
      "description": "最新科技产品，限时优惠",
      "image_url": "https://example.com/tech-ad.jpg",
      "landing_url": "https://example.com/tech-products"
    },
    "price": 0.65,
    "campaign_id": "camp_001",
    "impression_id": "imp_001"
  }
}
```

### 3.3 获取广告位库存
```http
GET /inventory
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "ad_slots": [
      {
        "slot_id": "slot_001",
        "size": "728x90",
        "position": "top",
        "floor_price": 0.3,
        "available": true
      },
      {
        "slot_id": "slot_002",
        "size": "300x250",
        "position": "sidebar",
        "floor_price": 0.25,
        "available": true
      }
    ],
    "total_slots": 2
  }
}
```

### 3.4 记录广告展示
```http
POST /impression
Content-Type: application/json

{
  "impression_id": "imp_001",
  "campaign_id": "camp_001",
  "user_id": "user_001",
  "price": 0.65,
  "slot_id": "slot_001"
}
```

### 3.5 获取收益报表
```http
GET /revenue
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "total_impressions": 25000,
    "total_revenue": 8750.0,
    "average_cpm": 35.0,
    "top_performing_slots": [
      {
        "slot_id": "slot_001",
        "impressions": 15000,
        "revenue": 5250.0,
        "cpm": 35.0
      }
    ],
    "period": {
      "start": "2024-01-01T00:00:00Z",
      "end": "2024-01-01T23:59:59Z"
    }
  }
}
```

## 4. 广告交易平台 (Ad Exchange) API

### 4.1 健康检查
```http
GET /health
```

### 4.2 处理实时竞价请求
```http
POST /rtb
Content-Type: application/json

{
  "id": "bid_req_001",
  "user_id": "user_001",
  "ad_slot": {
    "width": 728,
    "height": 90,
    "position": "top",
    "floor_price": 0.5
  },
  "device": {
    "type": "desktop",
    "os": "Windows",
    "browser": "Chrome"
  },
  "geo": {
    "country": "CN",
    "city": "北京"
  }
}
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "auction_id": "auction_001",
    "winning_bid": {
      "dsp_id": "dsp_001",
      "price": 0.75,
      "creative": {
        "title": "科技产品推荐",
        "image_url": "https://example.com/tech-ad.jpg"
      },
      "campaign_id": "camp_001"
    },
    "auction_price": 0.65,
    "duration_ms": 45
  }
}
```

### 4.3 获取竞价详情
```http
GET /auction/{auction_id}
```

### 4.4 演示完整 RTB 流程
```http
POST /demo/rtb-flow
Content-Type: application/json

{
  "user_id": "demo_user_001",
  "device_type": "desktop",
  "location": {"country": "CN", "city": "北京"}
}
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "demo_info": {
      "description": "Complete RTB workflow demonstration",
      "version": "1.0.0"
    },
    "workflow_result": {
      "workflow_id": "workflow_001",
      "status": "success",
      "duration_ms": 85.5,
      "steps": {
        "user_visit": {
          "user_id": "demo_user_001",
          "device_type": "desktop",
          "location": {"country": "CN", "city": "北京"}
        },
        "user_profile": {
          "interests": ["technology", "shopping"],
          "segments": ["tech_enthusiast"]
        },
        "auction_result": {
          "winning_bid": {
            "campaign_id": "camp_001",
            "price": 0.75
          },
          "auction_price": 0.65
        },
        "display_result": {
          "impression_confirmed": true,
          "impression_id": "imp_001"
        }
      }
    },
    "console_logs_note": "详细流程日志已输出到控制台"
  }
}
```

### 4.5 简化 RTB 演示
```http
POST /demo/rtb-flow-simple
```

**响应示例:**
```json
{
  "status": "success",
  "duration_ms": 85.5,
  "winning_campaign": "camp_001",
  "final_price": 0.65,
  "impression_confirmed": true,
  "workflow_id": "workflow_001"
}
```

### 4.6 获取工作流程统计
```http
GET /demo/workflow-stats
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "workflow_statistics": {
      "total_workflows": 100,
      "successful_workflows": 85,
      "failed_workflows": 15,
      "average_duration_ms": 78.5
    },
    "platform_statistics": {
      "total_auctions": 1000,
      "successful_auctions": 750,
      "average_auction_price": 0.68
    },
    "recent_auctions": [
      {
        "auction_id": "auction_001",
        "winning_price": 0.65,
        "timestamp": "2024-01-01T12:00:00Z"
      }
    ],
    "timestamp": "2024-01-01T12:00:00Z"
  }
}
```

### 4.7 重置演示统计
```http
POST /demo/reset-stats
```

## 5. 数据管理平台 (DMP) API

### 5.1 健康检查
```http
GET /health
```

### 5.2 获取用户画像
```http
GET /user/{user_id}/profile
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "user_id": "user_001",
    "demographics": {
      "age": 28,
      "gender": "male",
      "location": "北京"
    },
    "interests": ["technology", "shopping", "travel"],
    "behaviors": ["frequent_buyer", "mobile_user", "price_sensitive"],
    "segments": ["tech_enthusiast", "high_value", "young_professional"],
    "last_updated": "2024-01-01T12:00:00Z"
  }
}
```

### 5.3 记录用户行为
```http
POST /user/{user_id}/events
Content-Type: application/json

{
  "events": [
    {
      "event_type": "page_view",
      "page_url": "https://example.com/tech-products",
      "timestamp": "2024-01-01T12:00:00Z",
      "properties": {
        "category": "technology",
        "product_id": "prod_001"
      }
    },
    {
      "event_type": "click",
      "element": "product_link",
      "timestamp": "2024-01-01T12:01:00Z"
    }
  ]
}
```

### 5.4 更新用户画像
```http
PUT /user/{user_id}/profile
Content-Type: application/json

{
  "demographics": {
    "age": 29,
    "location": "上海"
  },
  "interests": ["technology", "shopping", "travel", "fitness"],
  "behaviors": ["frequent_buyer", "mobile_user"],
  "segments": ["tech_enthusiast", "high_value"]
}
```

### 5.5 获取用户分群
```http
GET /segments
```

**响应示例:**
```json
{
  "status": "success",
  "data": {
    "segments": [
      {
        "segment_id": "tech_enthusiast",
        "name": "科技爱好者",
        "description": "对科技产品感兴趣的用户",
        "user_count": 15000,
        "criteria": {
          "interests": ["technology", "gadgets"],
          "behaviors": ["tech_content_consumer"]
        }
      },
      {
        "segment_id": "high_value",
        "name": "高价值用户",
        "description": "消费能力较强的用户",
        "user_count": 8000,
        "criteria": {
          "behaviors": ["frequent_buyer", "high_spender"]
        }
      }
    ],
    "total": 2
  }
}
```

## 使用示例

### 完整 RTB 流程演示

#### 1. 启动演示流程
```bash
curl -X POST http://localhost:8004/demo/rtb-flow-simple \
  -H "Content-Type: application/json"
```

#### 2. 查看流程统计
```bash
curl http://localhost:8004/demo/workflow-stats
```

#### 3. 查看各服务健康状态
```bash
# 检查所有服务
for port in 8001 8002 8003 8004 8005; do
  echo "检查端口 $port:"
  curl -s http://localhost:$port/health | jq .
  echo ""
done
```

### 创建和管理广告活动

#### 1. 创建广告活动
```bash
curl -X POST http://localhost:8001/campaigns \
  -H "Content-Type: application/json" \
  -d '{
    "name": "测试活动",
    "advertiser_id": "test_advertiser",
    "budget": 5000.0,
    "targeting": {
      "age_range": {"min_age": 20, "max_age": 40},
      "interests": ["technology"]
    },
    "creative": {
      "title": "测试广告",
      "description": "这是一个测试广告"
    }
  }'
```

#### 2. 查看活动详情
```bash
# 假设返回的活动 ID 是 camp_123
curl http://localhost:8001/campaigns/camp_123
```

#### 3. 查看活动统计
```bash
curl http://localhost:8001/campaigns/camp_123/stats
```

### 用户画像管理

#### 1. 获取用户画像
```bash
curl http://localhost:8005/user/user_001/profile
```

#### 2. 记录用户行为
```bash
curl -X POST http://localhost:8005/user/user_001/events \
  -H "Content-Type: application/json" \
  -d '{
    "events": [
      {
        "event_type": "page_view",
        "page_url": "https://example.com/products",
        "timestamp": "2024-01-01T12:00:00Z"
      }
    ]
  }'
```

### 批量测试脚本

```bash
#!/bin/bash
# 批量测试所有 API 接口

echo "=== 健康检查 ==="
for port in 8001 8002 8003 8004 8005; do
  echo "端口 $port:"
  curl -s http://localhost:$port/health | jq '.status'
done

echo -e "\n=== RTB 演示 ==="
curl -X POST http://localhost:8004/demo/rtb-flow-simple | jq '.'

echo -e "\n=== 创建广告活动 ==="
CAMPAIGN_ID=$(curl -X POST http://localhost:8001/campaigns \
  -H "Content-Type: application/json" \
  -d '{"name":"API测试活动","advertiser_id":"test","budget":1000}' \
  | jq -r '.data.id')

echo "创建的活动 ID: $CAMPAIGN_ID"

echo -e "\n=== 获取活动详情 ==="
curl http://localhost:8001/campaigns/$CAMPAIGN_ID | jq '.'

echo -e "\n=== 测试完成 ==="
```

## 错误处理

### 常见错误码
- `INVALID_REQUEST` - 请求参数无效
- `CAMPAIGN_NOT_FOUND` - 广告活动未找到
- `USER_NOT_FOUND` - 用户未找到
- `BUDGET_EXCEEDED` - 预算不足
- `SERVICE_UNAVAILABLE` - 服务不可用
- `TIMEOUT` - 请求超时
- `DATABASE_ERROR` - 数据库错误

### 错误响应示例
```json
{
  "error_code": "CAMPAIGN_NOT_FOUND",
  "message": "Campaign with ID 'invalid_id' not found",
  "details": {
    "campaign_id": "invalid_id",
    "service": "ad-management"
  },
  "timestamp": "2024-01-01T12:00:00Z"
}
```

## 性能指标

### 响应时间要求
- 健康检查: < 10ms
- 广告活动 CRUD: < 100ms
- RTB 竞价: < 50ms
- 用户画像查询: < 50ms
- 完整 RTB 流程: < 100ms

### 并发处理能力
- 每个服务支持 100+ 并发请求
- RTB 流程支持 50+ 并发竞价
- 数据库操作支持连接池复用

## 开发和测试

### API 测试工具推荐
- **Postman** - GUI 测试工具
- **curl** - 命令行测试
- **httpie** - 友好的命令行工具
- **pytest** - 自动化测试

### 自动化测试
```bash
# 运行 API 集成测试
python -m pytest tests/test_*_service.py -v

# 运行 RTB 流程测试
python -m pytest tests/test_rtb_demo_flow.py -v

# 运行服务通信测试
python -m pytest tests/test_service_communication.py -v
```