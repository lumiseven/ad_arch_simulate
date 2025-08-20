"""
广告系统架构的共享数据模型

包含所有服务使用的Pydantic数据模型，提供数据验证和序列化功能。
这些模型定义了系统中各种实体的结构和验证规则：

核心模型：
- Campaign: 广告活动模型
- UserProfile: 用户画像模型  
- BidRequest/BidResponse: 竞价请求和响应模型
- Impression: 广告展示记录模型
- AuctionResult: 竞价结果模型
- UserEvent: 用户行为事件模型
- CampaignStats: 广告活动统计模型

辅助模型：
- AdSlot: 广告位信息模型
- Device: 设备信息模型
- Geo: 地理位置信息模型
- ErrorResponse: 标准错误响应模型
- HealthCheck: 健康检查响应模型

所有模型都包含完整的数据验证逻辑和字段描述。
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
import re


class CampaignStatus(str, Enum):
    """Campaign status enumeration."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    DRAFT = "draft"


class Campaign(BaseModel):
    """Advertisement campaign model."""
    id: str = Field(..., description="Unique campaign identifier", min_length=1)
    name: str = Field(..., description="Campaign name", min_length=1, max_length=255)
    advertiser_id: str = Field(..., description="Advertiser identifier", min_length=1)
    budget: float = Field(..., ge=0, description="Campaign budget")
    spent: float = Field(default=0.0, ge=0, description="Amount spent")
    targeting: Dict[str, Any] = Field(default_factory=dict, description="Targeting criteria")
    creative: Dict[str, Any] = Field(default_factory=dict, description="Creative content")
    status: CampaignStatus = Field(default=CampaignStatus.DRAFT, description="Campaign status")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.now, description="Last update timestamp")

    @model_validator(mode='after')
    def spent_cannot_exceed_budget(self):
        """Validate that spent amount doesn't exceed budget."""
        if self.spent > self.budget:
            raise ValueError('Spent amount cannot exceed budget')
        return self

    @field_validator('id', 'advertiser_id')
    @classmethod
    def validate_ids(cls, v):
        """Validate ID format."""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('ID must contain only alphanumeric characters, underscores, and hyphens')
        return v


class UserProfile(BaseModel):
    """User profile model for DMP."""
    user_id: str = Field(..., description="Unique user identifier", min_length=1)
    demographics: Dict[str, Any] = Field(default_factory=dict, description="User demographics")
    interests: List[str] = Field(default_factory=list, description="User interest tags")
    behaviors: List[str] = Field(default_factory=list, description="User behavior tags")
    segments: List[str] = Field(default_factory=list, description="User segments")
    last_updated: datetime = Field(default_factory=datetime.now, description="Last update timestamp")

    @field_validator('user_id')
    @classmethod
    def validate_user_id(cls, v):
        """Validate user ID format."""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('User ID must contain only alphanumeric characters, underscores, and hyphens')
        return v

    @field_validator('interests', 'behaviors', 'segments')
    @classmethod
    def validate_tags(cls, v):
        """Validate that tags are non-empty strings."""
        for tag in v:
            if not isinstance(tag, str) or not tag.strip():
                raise ValueError('Tags must be non-empty strings')
        return v


class AdSlot(BaseModel):
    """Advertisement slot information."""
    id: str = Field(..., description="Ad slot identifier")
    width: int = Field(..., gt=0, description="Ad slot width")
    height: int = Field(..., gt=0, description="Ad slot height")
    position: str = Field(..., description="Ad slot position")
    floor_price: float = Field(default=0.0, ge=0, description="Minimum bid price")


class Device(BaseModel):
    """Device information."""
    type: str = Field(..., description="Device type (mobile, desktop, tablet)")
    os: str = Field(..., description="Operating system")
    browser: str = Field(..., description="Browser name")
    ip: str = Field(..., description="IP address")

    @field_validator('type')
    @classmethod
    def validate_device_type(cls, v):
        """Validate device type."""
        allowed_types = ['mobile', 'desktop', 'tablet']
        if v.lower() not in allowed_types:
            raise ValueError(f'Device type must be one of: {allowed_types}')
        return v.lower()

    @field_validator('ip')
    @classmethod
    def validate_ip_address(cls, v):
        """Basic IP address validation."""
        # Simple IPv4 validation
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', v):
            raise ValueError('Invalid IP address format')
        return v


class Geo(BaseModel):
    """Geographic information."""
    country: str = Field(..., description="Country code")
    region: str = Field(..., description="Region/state")
    city: str = Field(..., description="City name")
    lat: Optional[float] = Field(None, description="Latitude")
    lon: Optional[float] = Field(None, description="Longitude")


class BidRequest(BaseModel):
    """Real-time bidding request."""
    id: str = Field(..., description="Unique request identifier")
    user_id: str = Field(..., description="User identifier")
    ad_slot: AdSlot = Field(..., description="Advertisement slot information")
    device: Device = Field(..., description="Device information")
    geo: Geo = Field(..., description="Geographic information")
    timestamp: datetime = Field(default_factory=datetime.now, description="Request timestamp")


class BidResponse(BaseModel):
    """Real-time bidding response."""
    request_id: str = Field(..., description="Original request identifier", min_length=1)
    price: float = Field(..., gt=0, description="Bid price")
    creative: Dict[str, Any] = Field(..., description="Creative content")
    campaign_id: str = Field(..., description="Campaign identifier", min_length=1)
    dsp_id: str = Field(..., description="DSP identifier", min_length=1)

    @field_validator('creative')
    @classmethod
    def validate_creative(cls, v):
        """Validate creative content has required fields."""
        required_fields = ['title']
        for field in required_fields:
            if field not in v or not v[field]:
                raise ValueError(f'Creative must contain non-empty {field}')
        return v

    @field_validator('price')
    @classmethod
    def validate_price_precision(cls, v):
        """Validate price has reasonable precision."""
        if round(v, 4) != v:
            raise ValueError('Price precision should not exceed 4 decimal places')
        return v


class Impression(BaseModel):
    """Advertisement impression record."""
    id: str = Field(..., description="Unique impression identifier")
    campaign_id: str = Field(..., description="Campaign identifier")
    user_id: str = Field(..., description="User identifier")
    price: float = Field(..., ge=0, description="Winning bid price")
    timestamp: datetime = Field(default_factory=datetime.now, description="Impression timestamp")
    revenue: float = Field(..., ge=0, description="Revenue generated")


class ErrorResponse(BaseModel):
    """Standard error response format."""
    error_code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional error details")
    timestamp: datetime = Field(default_factory=datetime.now, description="Error timestamp")


class HealthCheck(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service status")
    timestamp: datetime = Field(default_factory=datetime.now, description="Check timestamp")
    version: str = Field(default="0.1.0", description="Service version")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional health details")

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        """Validate health status."""
        allowed_statuses = ['healthy', 'unhealthy', 'degraded']
        if v.lower() not in allowed_statuses:
            raise ValueError(f'Status must be one of: {allowed_statuses}')
        return v.lower()


class AuctionResult(BaseModel):
    """Auction result model for Ad Exchange."""
    auction_id: str = Field(..., description="Unique auction identifier")
    request_id: str = Field(..., description="Original bid request ID")
    winning_bid: Optional[BidResponse] = Field(None, description="Winning bid response")
    all_bids: List[BidResponse] = Field(default_factory=list, description="All received bids")
    auction_price: float = Field(..., ge=0, description="Final auction price")
    timestamp: datetime = Field(default_factory=datetime.now, description="Auction completion time")


class UserEvent(BaseModel):
    """User behavior event for DMP."""
    event_id: str = Field(..., description="Unique event identifier")
    user_id: str = Field(..., description="User identifier")
    event_type: str = Field(..., description="Type of event (click, view, purchase, etc.)")
    event_data: Dict[str, Any] = Field(default_factory=dict, description="Event-specific data")
    timestamp: datetime = Field(default_factory=datetime.now, description="Event timestamp")

    @field_validator('event_type')
    @classmethod
    def validate_event_type(cls, v):
        """Validate event type."""
        allowed_types = ['click', 'view', 'purchase', 'signup', 'page_visit', 'search']
        if v.lower() not in allowed_types:
            raise ValueError(f'Event type must be one of: {allowed_types}')
        return v.lower()


class CampaignStats(BaseModel):
    """Campaign statistics model."""
    campaign_id: str = Field(..., description="Campaign identifier")
    impressions: int = Field(default=0, ge=0, description="Total impressions")
    clicks: int = Field(default=0, ge=0, description="Total clicks")
    conversions: int = Field(default=0, ge=0, description="Total conversions")
    spend: float = Field(default=0.0, ge=0, description="Total spend")
    revenue: float = Field(default=0.0, ge=0, description="Total revenue")
    ctr: float = Field(default=0.0, ge=0, le=1, description="Click-through rate")
    cpc: float = Field(default=0.0, ge=0, description="Cost per click")
    updated_at: datetime = Field(default_factory=datetime.now, description="Last update timestamp")

    @model_validator(mode='after')
    def calculate_derived_metrics(self):
        """Calculate derived metrics."""
        # Calculate CTR
        if self.impressions > 0:
            self.ctr = self.clicks / self.impressions
        
        # Calculate CPC
        if self.clicks > 0:
            self.cpc = self.spend / self.clicks
            
        return self