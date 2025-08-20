"""
Demand-Side Platform (DSP) main application.
FastAPI service for real-time bidding on behalf of advertisers.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import JSONResponse
from shared.utils import (
    setup_logging, ServiceConfig, APIClient, generate_id, 
    create_error_response, create_health_response, log_rtb_step
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
    """Core bidding engine for DSP."""
    
    def __init__(self):
        self.dsp_id = "dsp-001"
        self.min_bid = 0.01
        self.max_bid = 10.0
        self.default_frequency_cap = 5  # Max impressions per user per campaign per day
    
    async def evaluate_bid_request(self, bid_request: BidRequest) -> Optional[BidResponse]:
        """Evaluate bid request and return bid response if suitable."""
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
        """Calculate bid price based on campaign and user data."""
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
    """Health check endpoint."""
    details = {
        "active_campaigns": len([c for c in campaigns_db.values() if c.status.value == "active"]),
        "total_bid_requests": len(bid_history),
        "dsp_id": bidding_engine.dsp_id
    }
    
    return HealthCheck(status="healthy", details=details)


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