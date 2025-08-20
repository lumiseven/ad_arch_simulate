"""
Supply-Side Platform (SSP) main application.
FastAPI service for managing ad inventory and publisher revenue.
"""

import asyncio
import httpx
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from shared.utils import (
    setup_logging, ServiceConfig, create_error_response, 
    handle_service_error, ServiceError
)
from shared.models import (
    HealthCheck, BidRequest, BidResponse, Impression, ErrorResponse,
    AdSlot, Device, Geo, AuctionResult
)

# Service configuration
config = ServiceConfig("ssp")
logger = setup_logging("ssp")

# In-memory storage for demonstration
ad_inventory: Dict[str, "AdInventory"] = {}
impressions_data: List[Impression] = []
revenue_data: List["RevenueRecord"] = []


class AdInventory(BaseModel):
    """Ad inventory slot model."""
    slot_id: str = Field(..., description="Ad slot identifier")
    publisher_id: str = Field(..., description="Publisher identifier")
    ad_slot: AdSlot = Field(..., description="Ad slot specifications")
    available: bool = Field(default=True, description="Availability status")
    daily_impressions: int = Field(default=0, description="Daily impression count")
    total_revenue: float = Field(default=0.0, description="Total revenue generated")
    created_at: datetime = Field(default_factory=datetime.now)


class AdRequest(BaseModel):
    """Advertisement request from publisher."""
    slot_id: str = Field(..., description="Ad slot identifier")
    user_id: str = Field(..., description="User identifier")
    device: Device = Field(..., description="Device information")
    geo: Geo = Field(..., description="Geographic information")
    publisher_id: str = Field(..., description="Publisher identifier")


class AdResponse(BaseModel):
    """Advertisement response to publisher."""
    request_id: str = Field(..., description="Request identifier")
    creative: Dict = Field(..., description="Creative content")
    price: float = Field(..., description="Winning bid price")
    campaign_id: str = Field(..., description="Campaign identifier")
    impression_url: str = Field(..., description="Impression tracking URL")


class RevenueRecord(BaseModel):
    """Revenue tracking record."""
    slot_id: str
    publisher_id: str
    impression_id: str
    revenue: float
    timestamp: datetime = Field(default_factory=datetime.now)


class RevenueReport(BaseModel):
    """Revenue report model."""
    publisher_id: str
    total_revenue: float
    impressions_count: int
    average_cpm: float
    period_start: datetime
    period_end: datetime


class InventoryStats(BaseModel):
    """Inventory statistics model."""
    total_slots: int
    available_slots: int
    daily_impressions: int
    total_revenue: float
    average_fill_rate: float


def initialize_inventory():
    """Initialize sample ad inventory."""
    sample_slots = [
        {
            "slot_id": "banner_top_1",
            "publisher_id": "pub_001",
            "ad_slot": AdSlot(
                id="banner_top_1",
                width=728,
                height=90,
                position="top",
                floor_price=0.50
            )
        },
        {
            "slot_id": "sidebar_1",
            "publisher_id": "pub_001", 
            "ad_slot": AdSlot(
                id="sidebar_1",
                width=300,
                height=250,
                position="sidebar",
                floor_price=0.30
            )
        },
        {
            "slot_id": "mobile_banner_1",
            "publisher_id": "pub_002",
            "ad_slot": AdSlot(
                id="mobile_banner_1",
                width=320,
                height=50,
                position="top",
                floor_price=0.25
            )
        }
    ]
    
    for slot_data in sample_slots:
        inventory = AdInventory(**slot_data)
        ad_inventory[inventory.slot_id] = inventory
    
    logger.info(f"Initialized {len(sample_slots)} ad inventory slots")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the service on startup."""
    initialize_inventory()
    logger.info("SSP service started successfully")
    yield


# FastAPI application
app = FastAPI(
    title="Supply-Side Platform (SSP)",
    description="Service for managing ad inventory and maximizing publisher revenue",
    version="0.1.0",
    lifespan=lifespan
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


@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Enhanced health check endpoint."""
    try:
        # Check Ad Exchange connectivity
        ad_exchange_healthy = True
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get("http://localhost:8004/health")
                ad_exchange_healthy = response.status_code == 200
        except Exception:
            ad_exchange_healthy = False
        
        # Calculate service metrics
        total_slots = len(ad_inventory)
        available_slots = sum(1 for inv in ad_inventory.values() if inv.available)
        total_impressions = len(impressions_data)
        total_revenue = sum(inv.total_revenue for inv in ad_inventory.values())
        
        # Determine overall health
        status = "healthy"
        if not ad_exchange_healthy:
            status = "degraded"
        elif total_slots == 0:
            status = "unhealthy"
        
        return HealthCheck(
            status=status,
            details={
                "service": "ssp",
                "version": "0.1.0",
                "inventory_slots": total_slots,
                "available_slots": available_slots,
                "total_impressions": total_impressions,
                "total_revenue": round(total_revenue, 2),
                "fill_rate": round(available_slots / total_slots if total_slots > 0 else 0, 4),
                "dependencies": {
                    "ad-exchange": "healthy" if ad_exchange_healthy else "unhealthy"
                }
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthCheck(
            status="unhealthy",
            details={
                "service": "ssp",
                "error": str(e),
                "timestamp": datetime.now()
            }
        )


@app.post("/ad-request", response_model=AdResponse)
async def process_ad_request(request: AdRequest, background_tasks: BackgroundTasks):
    """
    Process advertisement request from publisher.
    Requirement 3.1: Handle ad requests from media pages.
    """
    logger.info(f"Processing ad request for slot {request.slot_id}")
    
    # Check if slot exists and is available
    if request.slot_id not in ad_inventory:
        raise HTTPException(status_code=404, detail="Ad slot not found")
    
    inventory = ad_inventory[request.slot_id]
    if not inventory.available:
        raise HTTPException(status_code=400, detail="Ad slot not available")
    
    # Create bid request for Ad Exchange
    bid_request = BidRequest(
        id=f"req_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
        user_id=request.user_id,
        ad_slot=inventory.ad_slot,
        device=request.device,
        geo=request.geo
    )
    
    try:
        # Send request to Ad Exchange
        winning_ad = await send_to_ad_exchange(bid_request)
        
        if winning_ad:
            # Record impression
            impression = Impression(
                id=f"imp_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
                campaign_id=winning_ad.campaign_id,
                user_id=request.user_id,
                price=winning_ad.price,
                revenue=calculate_revenue(winning_ad.price)
            )
            
            # Update inventory stats
            background_tasks.add_task(update_inventory_stats, request.slot_id, impression)
            
            return AdResponse(
                request_id=bid_request.id,
                creative=winning_ad.creative,
                price=winning_ad.price,
                campaign_id=winning_ad.campaign_id,
                impression_url=f"/impression/{impression.id}"
            )
        else:
            # No winning bid, return default ad or error
            raise HTTPException(status_code=204, detail="No ads available")
            
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Error processing ad request: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/inventory", response_model=List[AdInventory])
async def get_inventory(publisher_id: Optional[str] = None):
    """
    Get ad inventory information.
    Requirement 3.2: Provide inventory management and queries.
    """
    logger.info(f"Getting inventory for publisher: {publisher_id}")
    
    if publisher_id:
        # Filter by publisher
        filtered_inventory = [
            inv for inv in ad_inventory.values() 
            if inv.publisher_id == publisher_id
        ]
        return filtered_inventory
    
    return list(ad_inventory.values())


@app.get("/inventory/stats", response_model=InventoryStats)
async def get_inventory_stats():
    """Get overall inventory statistics."""
    total_slots = len(ad_inventory)
    available_slots = sum(1 for inv in ad_inventory.values() if inv.available)
    daily_impressions = sum(inv.daily_impressions for inv in ad_inventory.values())
    total_revenue = sum(inv.total_revenue for inv in ad_inventory.values())
    
    fill_rate = (daily_impressions / total_slots) if total_slots > 0 else 0.0
    
    return InventoryStats(
        total_slots=total_slots,
        available_slots=available_slots,
        daily_impressions=daily_impressions,
        total_revenue=total_revenue,
        average_fill_rate=fill_rate
    )


@app.get("/revenue", response_model=List[RevenueReport])
async def get_revenue_report(
    publisher_id: Optional[str] = None,
    days: int = 7
):
    """
    Get revenue report for publishers.
    Requirement 3.4: Provide detailed revenue reports.
    """
    logger.info(f"Generating revenue report for publisher: {publisher_id}, days: {days}")
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # Filter revenue data by date range and publisher
    filtered_revenue = [
        record for record in revenue_data
        if start_date <= record.timestamp <= end_date
        and (not publisher_id or record.publisher_id == publisher_id)
    ]
    
    # Group by publisher
    publisher_revenue = {}
    for record in filtered_revenue:
        pub_id = record.publisher_id
        if pub_id not in publisher_revenue:
            publisher_revenue[pub_id] = {
                'total_revenue': 0.0,
                'impressions': 0
            }
        publisher_revenue[pub_id]['total_revenue'] += record.revenue
        publisher_revenue[pub_id]['impressions'] += 1
    
    # Create reports
    reports = []
    for pub_id, data in publisher_revenue.items():
        avg_cpm = (data['total_revenue'] / data['impressions'] * 1000) if data['impressions'] > 0 else 0.0
        
        reports.append(RevenueReport(
            publisher_id=pub_id,
            total_revenue=data['total_revenue'],
            impressions_count=data['impressions'],
            average_cpm=avg_cpm,
            period_start=start_date,
            period_end=end_date
        ))
    
    return reports


@app.post("/impression/{impression_id}")
async def record_impression(impression_id: str, background_tasks: BackgroundTasks):
    """
    Record advertisement impression.
    Requirement 3.4: Track display data and statistics.
    """
    logger.info(f"Recording impression: {impression_id}")
    
    # Find the impression
    impression = next((imp for imp in impressions_data if imp.id == impression_id), None)
    if not impression:
        raise HTTPException(status_code=404, detail="Impression not found")
    
    # Update revenue tracking
    background_tasks.add_task(update_revenue_tracking, impression)
    
    return {"status": "recorded", "impression_id": impression_id}


async def send_to_ad_exchange(bid_request: BidRequest) -> Optional[BidResponse]:
    """
    Send bid request to Ad Exchange and get winning ad.
    Requirement 3.3: Implement revenue optimization by selecting highest bid.
    """
    try:
        async with httpx.AsyncClient(timeout=0.1) as client:  # 100ms timeout
            response = await client.post(
                f"http://localhost:8004/rtb",
                json=bid_request.model_dump(),
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                auction_data = response.json()
                auction_result = AuctionResult(**auction_data)
                return auction_result.winning_bid
            else:
                logger.warning(f"Ad Exchange returned status {response.status_code}")
                return None
                
    except httpx.TimeoutException:
        logger.warning("Ad Exchange request timed out")
        return None
    except Exception as e:
        logger.error(f"Error communicating with Ad Exchange: {str(e)}")
        return None


def calculate_revenue(winning_price: float) -> float:
    """
    Calculate revenue from winning bid price.
    Requirement 3.3: Revenue optimization algorithm.
    """
    # SSP typically takes a percentage of the winning bid
    ssp_fee_rate = 0.10  # 10% fee
    publisher_revenue = winning_price * (1 - ssp_fee_rate)
    return publisher_revenue


async def update_inventory_stats(slot_id: str, impression: Impression):
    """Update inventory statistics after impression."""
    if slot_id in ad_inventory:
        inventory = ad_inventory[slot_id]
        inventory.daily_impressions += 1
        inventory.total_revenue += impression.revenue
        
        # Store impression data
        impressions_data.append(impression)
        
        logger.info(f"Updated stats for slot {slot_id}: impressions={inventory.daily_impressions}, revenue={inventory.total_revenue}")


async def update_revenue_tracking(impression: Impression):
    """Update revenue tracking records."""
    # Find the slot for this impression
    slot_id = None
    publisher_id = None
    
    for inv in ad_inventory.values():
        if inv.slot_id in impressions_data:  # This is a simplified lookup
            slot_id = inv.slot_id
            publisher_id = inv.publisher_id
            break
    
    if slot_id and publisher_id:
        revenue_record = RevenueRecord(
            slot_id=slot_id,
            publisher_id=publisher_id,
            impression_id=impression.id,
            revenue=impression.revenue
        )
        revenue_data.append(revenue_record)
        
        logger.info(f"Recorded revenue: {impression.revenue} for publisher {publisher_id}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)