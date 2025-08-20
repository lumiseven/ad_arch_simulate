"""
需求方平台 (DSP) 主应用程序

这是需求方平台的核心服务，代表广告主参与实时竞价。
主要功能包括：
- 接收来自Ad Exchange的竞价请求
- 基于用户画像和广告活动进行竞价决策
- 管理广告活动预算和频次控制
- 记录竞价历史和统计数据
- 处理竞价成功通知

技术栈：
- FastAPI: Web框架
- asyncio: 异步处理
- Pydantic: 数据验证
- 内存存储: 演示用数据存储

端口: 8002
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from shared.utils import (
    setup_logging, ServiceConfig, APIClient, generate_id, 
    create_error_response, create_health_response, log_rtb_step,
    handle_service_error, ServiceError, with_error_handling
)
from shared.models import (
    HealthCheck, BidRequest, BidResponse, Campaign, UserProfile,
    CampaignStats, ErrorResponse
)

# Service configuration
config = ServiceConfig("dsp")
logger = setup_logging("dsp")

# FastAPI application
app = FastAPI(
    title="Demand-Side Platform (DSP)",
    description="Service for real-time bidding on behalf of advertisers",
    version="0.1.0"
)


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

# In-memory storage for demonstration
campaigns_db: Dict[str, Campaign] = {}
bid_history: List[Dict[str, Any]] = []
campaign_stats: Dict[str, CampaignStats] = {}
budget_tracking: Dict[str, Dict[str, Any]] = {}
frequency_caps: Dict[str, Dict[str, int]] = {}  # user_id -> campaign_id -> impression_count

# API clients
dmp_client = APIClient(config.get_service_url("dmp"))
ad_mgmt_client = APIClient(config.get_service_url("ad-management"))


class DSPBiddingEngine:
    """
    DSP核心竞价引擎
    
    负责DSP的竞价决策逻辑，包括：
    - 评估竞价请求的匹配度
    - 查询用户画像进行精准定向
    - 计算合理的竞价价格
    - 管理预算和频次控制
    - 记录竞价历史和统计
    """
    
    def __init__(self):
        """
        初始化DSP竞价引擎
        
        设置关键参数：
        - dsp_id: DSP唯一标识符
        - min_bid/max_bid: 竞价价格范围限制
        - default_frequency_cap: 默认频次上限(每用户每活动每天5次)
        """
        self.dsp_id = "dsp-001"
        self.min_bid = 0.01
        self.max_bid = 10.0
        self.default_frequency_cap = 5  # Max impressions per user per campaign per day
    
    async def evaluate_bid_request(self, bid_request: BidRequest) -> Optional[BidResponse]:
        """
        评估竞价请求并返回竞价响应
        
        这是DSP的核心竞价决策方法，执行以下流程：
        1. 从DMP获取用户画像数据
        2. 查找匹配的广告活动
        3. 检查预算和频次限制
        4. 计算合理的竞价价格
        5. 生成竞价响应
        
        参数:
            bid_request: 来自Ad Exchange的竞价请求
            
        返回:
            Optional[BidResponse]: 竞价响应，如果不参与竞价则返回None
            
        决策因素:
            - 用户画像匹配度
            - 广告活动定向条件
            - 剩余预算情况
            - 频次控制限制
            - 设备类型和地理位置
        """
        try:
            # Get user profile from DMP
            user_profile = await self._get_user_profile(bid_request.user_id)
            
            # Find matching campaigns
            matching_campaigns = self._find_matching_campaigns(bid_request, user_profile)
            
            if not matching_campaigns:
                logger.info(f"No matching campaigns for request {bid_request.id}")
                return None
            
            # Select best campaign and calculate bid
            selected_campaign = self._select_best_campaign(matching_campaigns, bid_request, user_profile)
            
            if not selected_campaign:
                return None
            
            # Check budget and frequency constraints
            if not self._check_constraints(selected_campaign, bid_request.user_id):
                logger.info(f"Budget or frequency constraints failed for campaign {selected_campaign.id}")
                return None
            
            # Calculate bid price
            bid_price = self._calculate_bid_price(selected_campaign, bid_request, user_profile)
            
            # Create bid response
            bid_response = BidResponse(
                request_id=bid_request.id,
                price=bid_price,
                creative=selected_campaign.creative,
                campaign_id=selected_campaign.id,
                dsp_id=self.dsp_id
            )
            
            # Log bidding decision
            log_rtb_step(logger, "DSP Bid Decision", {
                "request_id": bid_request.id,
                "campaign_id": selected_campaign.id,
                "bid_price": bid_price,
                "user_segments": user_profile.segments if user_profile else []
            })
            
            return bid_response
            
        except Exception as e:
            logger.error(f"Error evaluating bid request {bid_request.id}: {e}")
            return None
    
    async def _get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get user profile from DMP."""
        try:
            response = await dmp_client.get(f"/user/{user_id}/profile")
            return UserProfile.model_validate(response)
        except Exception as e:
            logger.warning(f"Failed to get user profile for {user_id}: {e}")
            return None
    
    def _find_matching_campaigns(self, bid_request: BidRequest, user_profile: Optional[UserProfile]) -> List[Campaign]:
        """Find campaigns that match the bid request and user profile."""
        matching_campaigns = []
        
        for campaign in campaigns_db.values():
            if campaign.status.value != "active":
                continue
            
            # Check if campaign has remaining budget
            if campaign.spent >= campaign.budget:
                continue
            
            # Check targeting criteria
            if self._matches_targeting(campaign, bid_request, user_profile):
                matching_campaigns.append(campaign)
        
        return matching_campaigns
    
    def _matches_targeting(self, campaign: Campaign, bid_request: BidRequest, user_profile: Optional[UserProfile]) -> bool:
        """Check if campaign targeting matches the bid request."""
        targeting = campaign.targeting
        
        # Device targeting
        if "device_types" in targeting:
            if bid_request.device.type not in targeting["device_types"]:
                return False
        
        # Geographic targeting
        if "countries" in targeting:
            if bid_request.geo.country not in targeting["countries"]:
                return False
        
        # User segment targeting
        if user_profile and "segments" in targeting:
            if not any(segment in user_profile.segments for segment in targeting["segments"]):
                return False
        
        # Interest targeting
        if user_profile and "interests" in targeting:
            if not any(interest in user_profile.interests for interest in targeting["interests"]):
                return False
        
        return True
    
    def _select_best_campaign(self, campaigns: List[Campaign], bid_request: BidRequest, user_profile: Optional[UserProfile]) -> Optional[Campaign]:
        """Select the best campaign from matching campaigns."""
        if not campaigns:
            return None
        
        # Simple selection: highest budget remaining
        best_campaign = max(campaigns, key=lambda c: c.budget - c.spent)
        return best_campaign
    
    def _check_constraints(self, campaign: Campaign, user_id: str) -> bool:
        """Check budget and frequency constraints."""
        # Budget check
        if campaign.spent >= campaign.budget:
            return False
        
        # Frequency cap check
        today = datetime.now().date().isoformat()
        user_freq = frequency_caps.get(user_id, {})
        campaign_freq = user_freq.get(campaign.id, {})
        daily_impressions = campaign_freq.get(today, 0)
        
        if daily_impressions >= self.default_frequency_cap:
            return False
        
        return True
    
    def _calculate_bid_price(self, campaign: Campaign, bid_request: BidRequest, user_profile: Optional[UserProfile]) -> float:
        """
        基于广告活动和用户数据计算竞价价格
        
        竞价价格计算逻辑：
        1. 设置基础竞价价格(0.5)
        2. 根据广告位底价调整(至少高出10%)
        3. 根据用户画像质量调整：
           - 兴趣和分群越多，价格越高
           - 每个兴趣/分群增加10%
        4. 根据设备类型调整：
           - 移动设备: +20%
           - 桌面设备: 基准价格
           - 平板设备: -10%
        5. 确保价格在允许范围内(0.01-10.0)
        6. 精确到4位小数
        
        参数:
            campaign: 匹配的广告活动
            bid_request: 竞价请求(包含设备和广告位信息)
            user_profile: 用户画像(可能为空)
            
        返回:
            float: 计算得出的竞价价格
            
        价格策略:
            - 优质用户画像获得更高出价
            - 移动流量获得溢价
            - 严格遵守底价要求
        """
        base_price = 0.5  # Base bid price
        
        # Adjust based on ad slot floor price
        if bid_request.ad_slot.floor_price > 0:
            base_price = max(base_price, bid_request.ad_slot.floor_price * 1.1)
        
        # Adjust based on user profile quality
        if user_profile:
            # Higher bid for users with more interests/segments
            profile_score = len(user_profile.interests) + len(user_profile.segments)
            base_price *= (1 + profile_score * 0.1)
        
        # Adjust based on device type
        device_multipliers = {
            "mobile": 1.2,
            "desktop": 1.0,
            "tablet": 0.9
        }
        base_price *= device_multipliers.get(bid_request.device.type, 1.0)
        
        # Ensure bid is within limits
        bid_price = max(self.min_bid, min(base_price, self.max_bid))
        
        # Round to 4 decimal places
        return round(bid_price, 4)
    
    def record_win(self, campaign_id: str, user_id: str, price: float):
        """Record a winning bid."""
        # Update campaign spend
        if campaign_id in campaigns_db:
            campaigns_db[campaign_id].spent += price
        
        # Update frequency cap
        today = datetime.now().date().isoformat()
        if user_id not in frequency_caps:
            frequency_caps[user_id] = {}
        if campaign_id not in frequency_caps[user_id]:
            frequency_caps[user_id][campaign_id] = {}
        if today not in frequency_caps[user_id][campaign_id]:
            frequency_caps[user_id][campaign_id][today] = 0
        frequency_caps[user_id][campaign_id][today] += 1
        
        # Update campaign stats
        if campaign_id not in campaign_stats:
            campaign_stats[campaign_id] = CampaignStats(campaign_id=campaign_id)
        
        stats = campaign_stats[campaign_id]
        stats.impressions += 1
        stats.spend += price
        stats.updated_at = datetime.now()


# Initialize bidding engine
bidding_engine = DSPBiddingEngine()


@app.post("/bid", response_model=BidResponse)
async def handle_bid_request(bid_request: BidRequest):
    """Handle real-time bidding request."""
    try:
        # Record bid request in history
        bid_history.append({
            "request_id": bid_request.id,
            "user_id": bid_request.user_id,
            "timestamp": datetime.now(),
            "ad_slot": bid_request.ad_slot.model_dump(),
            "device": bid_request.device.model_dump(),
            "geo": bid_request.geo.model_dump()
        })
        
        # Evaluate bid request
        bid_response = await bidding_engine.evaluate_bid_request(bid_request)
        
        if not bid_response:
            raise HTTPException(status_code=204, detail="No bid")
        
        # Record bid response in history
        bid_history[-1]["bid_response"] = bid_response.model_dump()
        
        return bid_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling bid request: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/campaigns", response_model=List[Campaign])
async def get_campaigns():
    """Get all campaigns associated with this DSP."""
    return list(campaigns_db.values())


@app.post("/campaigns", response_model=Campaign)
async def add_campaign(campaign: Campaign):
    """Add a new campaign to the DSP."""
    campaigns_db[campaign.id] = campaign
    
    # Initialize campaign stats
    campaign_stats[campaign.id] = CampaignStats(campaign_id=campaign.id)
    
    logger.info(f"Added campaign {campaign.id} to DSP")
    return campaign


@app.post("/win-notice")
async def handle_win_notice(data: Dict[str, Any]):
    """Handle win notice from Ad Exchange."""
    try:
        campaign_id = data.get("campaign_id")
        user_id = data.get("user_id")
        price = data.get("price", 0.0)
        
        if not all([campaign_id, user_id]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        # Record the win
        bidding_engine.record_win(campaign_id, user_id, price)
        
        log_rtb_step(logger, "DSP Win Notice", {
            "campaign_id": campaign_id,
            "user_id": user_id,
            "price": price
        })
        
        return {"status": "success", "message": "Win notice processed"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling win notice: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/stats", response_model=Dict[str, Any])
async def get_stats():
    """Get DSP statistics."""
    total_requests = len(bid_history)
    total_bids = len([h for h in bid_history if "bid_response" in h])
    
    stats = {
        "total_bid_requests": total_requests,
        "total_bids_submitted": total_bids,
        "bid_rate": total_bids / total_requests if total_requests > 0 else 0,
        "active_campaigns": len([c for c in campaigns_db.values() if c.status.value == "active"]),
        "total_spend": sum(c.spent for c in campaigns_db.values()),
        "campaign_stats": {cid: stats.model_dump() for cid, stats in campaign_stats.items()}
    }
    
    return stats


@app.get("/bid-history", response_model=List[Dict[str, Any]])
async def get_bid_history(limit: int = 100):
    """Get recent bid history."""
    return bid_history[-limit:]


@app.get("/campaigns/{campaign_id}/stats", response_model=CampaignStats)
async def get_campaign_stats(campaign_id: str):
    """Get statistics for a specific campaign."""
    if campaign_id not in campaign_stats:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    return campaign_stats[campaign_id]


@app.delete("/campaigns/{campaign_id}")
async def remove_campaign(campaign_id: str):
    """Remove a campaign from the DSP."""
    if campaign_id not in campaigns_db:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    del campaigns_db[campaign_id]
    if campaign_id in campaign_stats:
        del campaign_stats[campaign_id]
    
    logger.info(f"Removed campaign {campaign_id} from DSP")
    return {"status": "success", "message": "Campaign removed"}


@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Enhanced health check endpoint."""
    try:
        # Check service dependencies
        dependencies = {}
        
        # Test DMP connectivity
        try:
            await dmp_client.health_check()
            dependencies["dmp"] = "healthy"
        except Exception as e:
            dependencies["dmp"] = f"unhealthy: {str(e)}"
        
        # Test Ad Management connectivity
        try:
            await ad_mgmt_client.health_check()
            dependencies["ad-management"] = "healthy"
        except Exception as e:
            dependencies["ad-management"] = f"unhealthy: {str(e)}"
        
        # Calculate service metrics
        active_campaigns = len([c for c in campaigns_db.values() if c.status.value == "active"])
        total_requests = len(bid_history)
        total_bids = len([h for h in bid_history if "bid_response" in h])
        bid_rate = total_bids / total_requests if total_requests > 0 else 0
        
        # Determine overall health
        status = "healthy"
        unhealthy_deps = [k for k, v in dependencies.items() if "unhealthy" in v]
        if unhealthy_deps:
            status = "degraded"
        
        return HealthCheck(
            status=status,
            details={
                "service": "dsp",
                "version": "0.1.0",
                "dsp_id": bidding_engine.dsp_id,
                "active_campaigns": active_campaigns,
                "total_bid_requests": total_requests,
                "total_bids_submitted": total_bids,
                "bid_rate": round(bid_rate, 4),
                "dependencies": dependencies,
                "unhealthy_dependencies": unhealthy_deps
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthCheck(
            status="unhealthy",
            details={
                "service": "dsp",
                "error": str(e),
                "timestamp": datetime.now()
            }
        )


async def initialize_sample_campaigns():
    """Initialize DSP with sample campaigns."""
    # Sample campaigns for demonstration
    sample_campaigns = [
        Campaign(
            id="camp-001",
            name="Mobile Gaming Campaign",
            advertiser_id="adv-001",
            budget=1000.0,
            targeting={
                "device_types": ["mobile"],
                "interests": ["gaming", "mobile-apps"],
                "countries": ["US", "CA", "UK"]
            },
            creative={
                "title": "Play the Best Mobile Game!",
                "description": "Download now and get 100 free coins",
                "image_url": "https://example.com/game-ad.jpg"
            },
            status="active"
        ),
        Campaign(
            id="camp-002", 
            name="E-commerce Fashion Campaign",
            advertiser_id="adv-002",
            budget=2000.0,
            targeting={
                "device_types": ["desktop", "mobile"],
                "interests": ["fashion", "shopping"],
                "segments": ["high-income", "fashion-enthusiast"],
                "countries": ["US", "UK", "FR"]
            },
            creative={
                "title": "Latest Fashion Trends",
                "description": "Shop the newest collection with 30% off",
                "image_url": "https://example.com/fashion-ad.jpg"
            },
            status="active"
        )
    ]
    
    for campaign in sample_campaigns:
        campaigns_db[campaign.id] = campaign
        campaign_stats[campaign.id] = CampaignStats(campaign_id=campaign.id)
    
    logger.info(f"DSP initialized with {len(sample_campaigns)} sample campaigns")


# Initialize sample campaigns on startup
@app.on_event("startup")
async def startup_event():
    """Startup event handler."""
    await initialize_sample_campaigns()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)