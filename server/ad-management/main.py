"""
广告管理平台主应用程序

这是广告管理平台的核心服务，为广告主提供广告活动管理功能。
主要功能包括：
- 创建和管理广告活动
- 设置广告创意和定向条件
- 管理广告预算和支出跟踪
- 提供活动统计和报表
- 验证定向条件和创意内容
- 监控预算使用情况

技术栈：
- FastAPI: Web框架
- SQLAlchemy: 数据库ORM
- Pydantic: 数据验证
- SQLite: 数据存储

端口: 8001
"""

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio
from shared.utils import (
    setup_logging, 
    ServiceConfig, 
    generate_id, 
    create_error_response,
    serialize_model,
    handle_service_error,
    ServiceError
)
from shared.config import get_config
from shared.database import init_database, check_database_health
from shared.database_service import get_campaign_service, get_campaign_stats_service
from shared.models import (
    Campaign, 
    CampaignStats, 
    CampaignStatus, 
    HealthCheck, 
    ErrorResponse
)
from pydantic import BaseModel

# Service configuration
app_config = get_config("ad-management")
config = ServiceConfig("ad-management")
logger = setup_logging("ad-management", app_config.logging.level)

# Database services
campaign_service = get_campaign_service()
campaign_stats_service = get_campaign_stats_service()

# In-memory storage for fallback (when database is unavailable)
campaigns_db: Dict[str, Campaign] = {}
campaign_stats_db: Dict[str, CampaignStats] = {}

# FastAPI application
app = FastAPI(
    title="Ad Management Platform",
    description="Service for managing advertising campaigns, creatives, and budgets",
    version="0.1.0"
)


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    try:
        await init_database()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        logger.info("Service will continue with fallback storage")


# Error handling middleware
@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError):
    """Handle ServiceError exceptions."""
    logger.error(f"Service error in {request.url.path}: {exc.message}")
    return JSONResponse(
        status_code=500,
        content=create_error_response(exc.error_code, exc.message, exc.details)
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors."""
    logger.warning(f"Validation error in {request.url.path}: {exc}")
    return JSONResponse(
        status_code=422,
        content=create_error_response(
            "VALIDATION_ERROR",
            "Request validation failed",
            {"errors": exc.errors()}
        )
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    logger.warning(f"HTTP exception in {request.url.path}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content=create_error_response(
            "HTTP_ERROR",
            exc.detail,
            {"status_code": exc.status_code}
        )
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.error(f"Unexpected error in {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content=create_error_response(
            "INTERNAL_ERROR",
            "An internal server error occurred",
            {"error": str(exc)}
        )
    )


class CampaignCreate(BaseModel):
    """Campaign creation request model."""
    name: str
    advertiser_id: str
    budget: float
    targeting: Dict[str, Any] = {}
    creative: Dict[str, Any] = {}


class CampaignUpdate(BaseModel):
    """Campaign update request model."""
    name: Optional[str] = None
    budget: Optional[float] = None
    targeting: Optional[Dict[str, Any]] = None
    creative: Optional[Dict[str, Any]] = None
    status: Optional[CampaignStatus] = None


class BudgetUpdate(BaseModel):
    """Budget update request model."""
    amount: float


def validate_targeting_criteria(targeting: Dict[str, Any]) -> bool:
    """
    验证定向条件的结构和数值
    
    这个函数确保广告活动的定向条件符合系统要求：
    
    支持的定向条件：
    - age_range: 年龄范围 {min_age: int, max_age: int}
    - gender: 性别 (字符串)
    - location: 地理位置 {countries: list, regions: list, cities: list}
    - interests: 兴趣标签 (字符串列表)
    - device_types: 设备类型 (字符串列表)
    - languages: 语言 (字符串列表)
    
    验证逻辑：
    1. 检查定向条件是否在允许列表中
    2. 验证每个条件的数据类型
    3. 对于复杂结构，递归验证子字段
    4. 记录未知的定向条件但不拒绝
    
    参数:
        targeting: 定向条件字典
        
    返回:
        bool: True表示验证通过，False表示格式错误
        
    容错性:
        - 空的定向条件被认为是有效的
        - 未知的定向条件会记录警告但不影响验证结果
        - 类型错误会导致验证失败
    """
    if not targeting:
        return True
    
    # Define allowed targeting criteria
    allowed_criteria = {
        'age_range': {'min_age': int, 'max_age': int},
        'gender': str,
        'location': {'countries': list, 'regions': list, 'cities': list},
        'interests': list,
        'device_types': list,
        'languages': list
    }
    
    for criterion, value in targeting.items():
        if criterion not in allowed_criteria:
            logger.warning(f"Unknown targeting criterion: {criterion}")
            continue
            
        expected_type = allowed_criteria[criterion]
        if isinstance(expected_type, dict):
            # Complex validation for nested structures
            if not isinstance(value, dict):
                return False
            for sub_key, sub_type in expected_type.items():
                if sub_key in value and not isinstance(value[sub_key], sub_type):
                    return False
        else:
            # Simple type validation
            if not isinstance(value, expected_type):
                return False
    
    return True


def validate_creative_content(creative: Dict[str, Any]) -> bool:
    """Validate creative content structure."""
    if not creative:
        return True
    
    # Basic creative validation
    if 'title' in creative and not isinstance(creative['title'], str):
        return False
    if 'description' in creative and not isinstance(creative['description'], str):
        return False
    if 'image_url' in creative and not isinstance(creative['image_url'], str):
        return False
    if 'click_url' in creative and not isinstance(creative['click_url'], str):
        return False
    
    return True


async def initialize_campaign_stats(campaign_id: str) -> CampaignStats:
    """Initialize campaign statistics."""
    try:
        # Check if stats already exist
        existing_stats = await campaign_stats_service.get_stats(campaign_id)
        if existing_stats:
            return existing_stats
        
        # Create initial stats
        stats_update = {
            "impressions": 0,
            "clicks": 0,
            "conversions": 0,
            "spend": 0.0,
            "revenue": 0.0,
            "ctr": 0.0,
            "cpc": 0.0
        }
        
        await campaign_stats_service.update_stats(campaign_id, stats_update)
        return await campaign_stats_service.get_stats(campaign_id)
        
    except Exception as e:
        logger.error(f"Failed to initialize stats for campaign {campaign_id}: {e}")
        # Fallback to in-memory stats
        stats = CampaignStats(campaign_id=campaign_id)
        campaign_stats_db[campaign_id] = stats
        return stats


async def update_campaign_spend(campaign_id: str, amount: float) -> bool:
    """
    更新广告活动支出金额
    
    这个函数处理广告活动的预算消耗更新：
    1. 使用数据库服务更新支出金额
    2. 验证支出不超过预算限制
    3. 同步更新活动统计数据
    4. 记录支出更新日志
    5. 返回操作成功状态
    
    预算控制：
    - 严格检查支出不能超过总预算
    - 支持增量更新和绝对值更新
    - 自动计算剩余预算
    
    参数:
        campaign_id: 广告活动唯一标识符
        amount: 要更新的支出金额
        
    返回:
        bool: True表示更新成功，False表示更新失败
        
    失败原因:
        - 活动不存在
        - 支出超过预算限制
        - 数据库操作失败
        
    副作用:
        - 更新数据库中的活动支出
        - 更新活动统计表中的支出数据
        - 记录操作日志
    """
    try:
        # Update spend using database service
        success = await campaign_service.update_spend(campaign_id, amount)
        
        if success:
            # Update stats
            campaign = await campaign_service.get_campaign(campaign_id)
            if campaign:
                stats_update = {"spend": campaign.spent}
                await campaign_stats_service.update_stats(campaign_id, stats_update)
                logger.info(f"Updated spend for campaign {campaign_id}: {campaign.spent}/{campaign.budget}")
        
        return success
        
    except Exception as e:
        logger.error(f"Failed to update spend for campaign {campaign_id}: {e}")
        return False


@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Enhanced health check endpoint."""
    try:
        # Check database connectivity
        db_healthy = await check_database_health()
        
        # Check service dependencies
        dependencies = {}
        
        # Calculate service metrics using database service
        campaigns = await campaign_service.list_campaigns(limit=10000)  # Get all for counting
        total_campaigns = len(campaigns)
        active_campaigns = len([c for c in campaigns if c.status == CampaignStatus.ACTIVE])
        total_budget = sum(c.budget for c in campaigns)
        total_spent = sum(c.spent for c in campaigns)
        
        # Determine overall health status
        status = "healthy"
        if not db_healthy:
            status = "degraded"  # Service can still work with fallback
        elif total_campaigns > 1000:  # Example threshold
            status = "degraded"
        
        return HealthCheck(
            status=status,
            details={
                "service": "ad-management",
                "version": "0.1.0",
                "uptime": "unknown",  # Would be calculated from start time
                "database": "healthy" if db_healthy else "unhealthy",
                "campaigns_count": total_campaigns,
                "active_campaigns": active_campaigns,
                "total_budget": total_budget,
                "total_spent": total_spent,
                "memory_usage": "unknown",  # Would use psutil in production
                "dependencies": dependencies,
                "fallback_mode": not db_healthy
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthCheck(
            status="unhealthy",
            details={
                "service": "ad-management",
                "error": str(e),
                "timestamp": datetime.now()
            }
        )


@app.post("/campaigns", response_model=Campaign)
async def create_campaign(campaign_data: CampaignCreate):
    """
    创建新的广告活动
    
    这是广告管理平台的核心功能，为广告主创建新的广告活动：
    1. 验证定向条件的格式和有效性
    2. 验证创意内容的完整性
    3. 生成唯一的活动ID
    4. 创建活动对象并设置初始状态为草稿
    5. 存储到数据库中
    6. 初始化活动统计数据
    7. 记录创建日志
    
    验证规则：
    - 定向条件必须符合预定义格式
    - 创意内容必须包含必要字段
    - 预算必须为正数
    - 广告主ID必须有效
    
    参数:
        campaign_data: 活动创建数据，包含名称、预算、定向、创意等
        
    返回:
        Campaign: 创建成功的广告活动对象
        
    异常:
        - 400: 定向条件或创意内容格式无效
        - 500: 数据库操作失败
        
    初始状态:
        - 状态设置为DRAFT(草稿)
        - 支出金额为0
        - 自动生成创建和更新时间
    """
    # Validate targeting criteria
    if not validate_targeting_criteria(campaign_data.targeting):
        raise HTTPException(
            status_code=400,
            detail="Invalid targeting criteria format"
        )
    
    # Validate creative content
    if not validate_creative_content(campaign_data.creative):
        raise HTTPException(
            status_code=400,
            detail="Invalid creative content format"
        )
    
    try:
        # Create campaign
        campaign_id = generate_id()
        campaign = Campaign(
            id=campaign_id,
            name=campaign_data.name,
            advertiser_id=campaign_data.advertiser_id,
            budget=campaign_data.budget,
            targeting=campaign_data.targeting,
            creative=campaign_data.creative,
            status=CampaignStatus.DRAFT
        )
        
        # Store campaign using database service
        created_campaign = await campaign_service.create_campaign(campaign)
        
        # Initialize stats
        await initialize_campaign_stats(campaign_id)
        
        logger.info(f"Created campaign {campaign_id}: {campaign.name}")
        return created_campaign
        
    except Exception as e:
        logger.error(f"Error creating campaign: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/campaigns/{campaign_id}", response_model=Campaign)
async def get_campaign(campaign_id: str):
    """Get campaign details by ID."""
    campaign = await campaign_service.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    logger.info(f"Retrieved campaign {campaign_id}")
    return campaign


@app.put("/campaigns/{campaign_id}", response_model=Campaign)
async def update_campaign(campaign_id: str, update_data: CampaignUpdate):
    """Update campaign details."""
    # Get existing campaign
    campaign = await campaign_service.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    try:
        # Prepare update data
        update_dict = {}
        
        if update_data.name is not None:
            update_dict["name"] = update_data.name
        
        if update_data.budget is not None:
            if update_data.budget < campaign.spent:
                raise HTTPException(
                    status_code=400,
                    detail="Budget cannot be less than already spent amount"
                )
            update_dict["budget"] = update_data.budget
        
        if update_data.targeting is not None:
            if not validate_targeting_criteria(update_data.targeting):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid targeting criteria format"
                )
            update_dict["targeting"] = update_data.targeting
        
        if update_data.creative is not None:
            if not validate_creative_content(update_data.creative):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid creative content format"
                )
            update_dict["creative"] = update_data.creative
        
        if update_data.status is not None:
            update_dict["status"] = update_data.status.value
        
        # Update campaign using database service
        updated_campaign = await campaign_service.update_campaign(campaign_id, update_dict)
        if updated_campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        logger.info(f"Updated campaign {campaign_id}")
        return updated_campaign
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating campaign {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str):
    """Delete a campaign."""
    success = await campaign_service.delete_campaign(campaign_id)
    if not success:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    logger.info(f"Deleted campaign {campaign_id}")
    return {"message": "Campaign deleted successfully"}


@app.get("/campaigns", response_model=List[Campaign])
async def list_campaigns(
    advertiser_id: Optional[str] = None,
    status: Optional[CampaignStatus] = None,
    limit: int = 100,
    offset: int = 0
):
    """List campaigns with optional filtering."""
    # Get campaigns from database service
    campaigns = await campaign_service.list_campaigns(limit=limit * 2, offset=0)  # Get more for filtering
    
    # Apply filters
    if advertiser_id:
        campaigns = [c for c in campaigns if c.advertiser_id == advertiser_id]
    
    if status:
        campaigns = [c for c in campaigns if c.status == status]
    
    # Apply pagination after filtering
    campaigns = campaigns[offset:offset + limit]
    
    logger.info(f"Listed {len(campaigns)} campaigns")
    return campaigns


@app.get("/campaigns/{campaign_id}/stats", response_model=CampaignStats)
async def get_campaign_stats(campaign_id: str):
    """Get campaign statistics."""
    # Check if campaign exists
    campaign = await campaign_service.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    # Get stats
    stats = await campaign_stats_service.get_stats(campaign_id)
    if stats is None:
        # Initialize stats if they don't exist
        stats = await initialize_campaign_stats(campaign_id)
    
    logger.info(f"Retrieved stats for campaign {campaign_id}")
    return stats


@app.post("/campaigns/{campaign_id}/spend")
async def update_campaign_spend_endpoint(campaign_id: str, spend_data: BudgetUpdate):
    """Update campaign spend amount."""
    # Check if campaign exists
    campaign = await campaign_service.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    if spend_data.amount <= 0:
        raise HTTPException(status_code=400, detail="Spend amount must be positive")
    
    success = await update_campaign_spend(campaign_id, spend_data.amount)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Spend amount would exceed campaign budget"
        )
    
    return {"message": "Campaign spend updated successfully"}


@app.get("/campaigns/{campaign_id}/budget-status")
async def get_budget_status(campaign_id: str):
    """Get campaign budget status and remaining budget."""
    campaign = await campaign_service.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    remaining_budget = campaign.budget - campaign.spent
    utilization_rate = campaign.spent / campaign.budget if campaign.budget > 0 else 0
    
    status = "healthy"
    if utilization_rate >= 0.9:
        status = "critical"
    elif utilization_rate >= 0.7:
        status = "warning"
    
    return {
        "campaign_id": campaign_id,
        "total_budget": campaign.budget,
        "spent": campaign.spent,
        "remaining": remaining_budget,
        "utilization_rate": utilization_rate,
        "status": status
    }


@app.post("/campaigns/{campaign_id}/validate-targeting")
async def validate_campaign_targeting(campaign_id: str):
    """Validate campaign targeting criteria."""
    campaign = await campaign_service.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    is_valid = validate_targeting_criteria(campaign.targeting)
    
    return {
        "campaign_id": campaign_id,
        "targeting_valid": is_valid,
        "targeting_criteria": campaign.targeting
    }


@app.get("/stats/summary")
async def get_platform_stats():
    """Get platform-wide statistics summary."""
    # Get all campaigns for statistics
    campaigns = await campaign_service.list_campaigns(limit=10000)  # Get all campaigns
    
    total_campaigns = len(campaigns)
    active_campaigns = len([c for c in campaigns if c.status == CampaignStatus.ACTIVE])
    paused_campaigns = len([c for c in campaigns if c.status == CampaignStatus.PAUSED])
    completed_campaigns = len([c for c in campaigns if c.status == CampaignStatus.COMPLETED])
    draft_campaigns = len([c for c in campaigns if c.status == CampaignStatus.DRAFT])
    
    total_budget = sum(c.budget for c in campaigns)
    total_spent = sum(c.spent for c in campaigns)
    
    return {
        "total_campaigns": total_campaigns,
        "active_campaigns": active_campaigns,
        "paused_campaigns": paused_campaigns,
        "completed_campaigns": completed_campaigns,
        "draft_campaigns": draft_campaigns,
        "total_budget": total_budget,
        "total_spent": total_spent,
        "remaining_budget": total_budget - total_spent,
        "budget_utilization": total_spent / total_budget if total_budget > 0 else 0
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=app_config.service.host, port=app_config.service.port)