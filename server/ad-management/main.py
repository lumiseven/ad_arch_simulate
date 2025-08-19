"""
Ad Management Platform main application.
FastAPI service for managing advertising campaigns.
"""

from fastapi import FastAPI, HTTPException, Depends
from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio
from shared.utils import (
    setup_logging, 
    ServiceConfig, 
    generate_id, 
    create_error_response,
    serialize_model
)
from shared.models import (
    Campaign, 
    CampaignStats, 
    CampaignStatus, 
    HealthCheck, 
    ErrorResponse
)
from pydantic import BaseModel

# Service configuration
config = ServiceConfig("ad-management")
logger = setup_logging("ad-management")

# In-memory storage for campaigns and stats (in production, use a database)
campaigns_db: Dict[str, Campaign] = {}
campaign_stats_db: Dict[str, CampaignStats] = {}

# FastAPI application
app = FastAPI(
    title="Ad Management Platform",
    description="Service for managing advertising campaigns, creatives, and budgets",
    version="0.1.0"
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
    """Validate targeting criteria structure and values."""
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


def calculate_campaign_stats(campaign_id: str) -> CampaignStats:
    """Calculate or retrieve campaign statistics."""
    if campaign_id in campaign_stats_db:
        return campaign_stats_db[campaign_id]
    
    # Create initial stats if not exists
    stats = CampaignStats(campaign_id=campaign_id)
    campaign_stats_db[campaign_id] = stats
    return stats


def update_campaign_spend(campaign_id: str, amount: float) -> bool:
    """Update campaign spend amount."""
    if campaign_id not in campaigns_db:
        return False
    
    campaign = campaigns_db[campaign_id]
    new_spent = campaign.spent + amount
    
    # Check budget constraints
    if new_spent > campaign.budget:
        logger.warning(f"Spend amount {new_spent} exceeds budget {campaign.budget} for campaign {campaign_id}")
        return False
    
    campaign.spent = new_spent
    campaign.updated_at = datetime.now()
    
    # Update stats
    stats = calculate_campaign_stats(campaign_id)
    stats.spend = new_spent
    stats.updated_at = datetime.now()
    
    logger.info(f"Updated spend for campaign {campaign_id}: {new_spent}/{campaign.budget}")
    return True


@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint."""
    return HealthCheck(
        status="healthy",
        details={
            "campaigns_count": len(campaigns_db),
            "active_campaigns": len([c for c in campaigns_db.values() if c.status == CampaignStatus.ACTIVE])
        }
    )


@app.post("/campaigns", response_model=Campaign)
async def create_campaign(campaign_data: CampaignCreate):
    """Create a new advertising campaign."""
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
        
        # Store campaign
        campaigns_db[campaign_id] = campaign
        
        # Initialize stats
        calculate_campaign_stats(campaign_id)
        
        logger.info(f"Created campaign {campaign_id}: {campaign.name}")
        return campaign
        
    except Exception as e:
        logger.error(f"Error creating campaign: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/campaigns/{campaign_id}", response_model=Campaign)
async def get_campaign(campaign_id: str):
    """Get campaign details by ID."""
    if campaign_id not in campaigns_db:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    campaign = campaigns_db[campaign_id]
    logger.info(f"Retrieved campaign {campaign_id}")
    return campaign


@app.put("/campaigns/{campaign_id}", response_model=Campaign)
async def update_campaign(campaign_id: str, update_data: CampaignUpdate):
    """Update campaign details."""
    if campaign_id not in campaigns_db:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    campaign = campaigns_db[campaign_id]
    
    try:
        # Update fields if provided
        if update_data.name is not None:
            campaign.name = update_data.name
        
        if update_data.budget is not None:
            if update_data.budget < campaign.spent:
                raise HTTPException(
                    status_code=400,
                    detail="Budget cannot be less than already spent amount"
                )
            campaign.budget = update_data.budget
        
        if update_data.targeting is not None:
            if not validate_targeting_criteria(update_data.targeting):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid targeting criteria format"
                )
            campaign.targeting = update_data.targeting
        
        if update_data.creative is not None:
            if not validate_creative_content(update_data.creative):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid creative content format"
                )
            campaign.creative = update_data.creative
        
        if update_data.status is not None:
            campaign.status = update_data.status
        
        campaign.updated_at = datetime.now()
        
        logger.info(f"Updated campaign {campaign_id}")
        return campaign
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating campaign {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str):
    """Delete a campaign."""
    if campaign_id not in campaigns_db:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    # Remove campaign and its stats
    del campaigns_db[campaign_id]
    if campaign_id in campaign_stats_db:
        del campaign_stats_db[campaign_id]
    
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
    campaigns = list(campaigns_db.values())
    
    # Apply filters
    if advertiser_id:
        campaigns = [c for c in campaigns if c.advertiser_id == advertiser_id]
    
    if status:
        campaigns = [c for c in campaigns if c.status == status]
    
    # Apply pagination
    campaigns = campaigns[offset:offset + limit]
    
    logger.info(f"Listed {len(campaigns)} campaigns")
    return campaigns


@app.get("/campaigns/{campaign_id}/stats", response_model=CampaignStats)
async def get_campaign_stats(campaign_id: str):
    """Get campaign statistics."""
    if campaign_id not in campaigns_db:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    stats = calculate_campaign_stats(campaign_id)
    logger.info(f"Retrieved stats for campaign {campaign_id}")
    return stats


@app.post("/campaigns/{campaign_id}/spend")
async def update_campaign_spend_endpoint(campaign_id: str, spend_data: BudgetUpdate):
    """Update campaign spend amount."""
    if campaign_id not in campaigns_db:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    if spend_data.amount <= 0:
        raise HTTPException(status_code=400, detail="Spend amount must be positive")
    
    success = update_campaign_spend(campaign_id, spend_data.amount)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Spend amount would exceed campaign budget"
        )
    
    return {"message": "Campaign spend updated successfully"}


@app.get("/campaigns/{campaign_id}/budget-status")
async def get_budget_status(campaign_id: str):
    """Get campaign budget status and remaining budget."""
    if campaign_id not in campaigns_db:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    campaign = campaigns_db[campaign_id]
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
    if campaign_id not in campaigns_db:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    campaign = campaigns_db[campaign_id]
    is_valid = validate_targeting_criteria(campaign.targeting)
    
    return {
        "campaign_id": campaign_id,
        "targeting_valid": is_valid,
        "targeting_criteria": campaign.targeting
    }


@app.get("/stats/summary")
async def get_platform_stats():
    """Get platform-wide statistics summary."""
    total_campaigns = len(campaigns_db)
    active_campaigns = len([c for c in campaigns_db.values() if c.status == CampaignStatus.ACTIVE])
    total_budget = sum(c.budget for c in campaigns_db.values())
    total_spent = sum(c.spent for c in campaigns_db.values())
    
    return {
        "total_campaigns": total_campaigns,
        "active_campaigns": active_campaigns,
        "paused_campaigns": len([c for c in campaigns_db.values() if c.status == CampaignStatus.PAUSED]),
        "completed_campaigns": len([c for c in campaigns_db.values() if c.status == CampaignStatus.COMPLETED]),
        "draft_campaigns": len([c for c in campaigns_db.values() if c.status == CampaignStatus.DRAFT]),
        "total_budget": total_budget,
        "total_spent": total_spent,
        "remaining_budget": total_budget - total_spent,
        "budget_utilization": total_spent / total_budget if total_budget > 0 else 0
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)