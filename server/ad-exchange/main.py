"""
Ad Exchange main application.
FastAPI service for real-time bidding coordination between DSPs and SSPs.
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from shared.utils import (
    setup_logging, ServiceConfig, APIClient, generate_id, 
    create_error_response, create_health_response, log_rtb_step,
    calculate_auction_metrics, handle_service_error, ServiceError
)
from shared.models import (
    HealthCheck, BidRequest, BidResponse, AuctionResult,
    ErrorResponse, UserProfile, Impression, AdSlot, Device, Geo
)

# Service configuration
config = ServiceConfig("ad-exchange")
logger = setup_logging("ad-exchange")

# FastAPI application
app = FastAPI(
    title="Ad Exchange",
    description="Real-time bidding coordination platform",
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
auction_history: Dict[str, AuctionResult] = {}
transaction_records: List[Dict[str, Any]] = []
platform_stats: Dict[str, Any] = {
    "total_auctions": 0,
    "successful_auctions": 0,
    "total_revenue": 0.0,
    "average_cpm": 0.0
}

# API clients for DSP services
dsp_clients = {
    "dsp": APIClient(config.get_service_url("dsp"), timeout=0.05),  # 50ms timeout
}

# API clients for other services
ssp_client = APIClient(config.get_service_url("ssp"))
dmp_client = APIClient(config.get_service_url("dmp"))


class AdExchangeEngine:
    """Core auction engine for Ad Exchange."""
    
    def __init__(self):
        self.exchange_id = "adx-001"
        self.auction_timeout = 0.1  # 100ms total auction timeout
        self.dsp_timeout = 0.05     # 50ms per DSP timeout
        self.platform_fee_rate = 0.1  # 10% platform fee
        self.second_price_auction = True  # Use second-price auction
    
    async def conduct_auction(self, bid_request: BidRequest) -> AuctionResult:
        """Conduct RTB auction for the given bid request."""
        auction_id = generate_id()
        start_time = datetime.now()
        
        log_rtb_step(logger, "Ad Exchange Auction Start", {
            "auction_id": auction_id,
            "request_id": bid_request.id,
            "user_id": bid_request.user_id,
            "ad_slot": f"{bid_request.ad_slot.width}x{bid_request.ad_slot.height}",
            "floor_price": bid_request.ad_slot.floor_price
        })
        
        try:
            # Send bid requests to all DSPs in parallel
            bid_responses = await self._collect_bids(bid_request)
            
            # Evaluate and rank bids
            winning_bid, auction_price = self._evaluate_bids(bid_responses, bid_request)
            
            # Create auction result
            auction_result = AuctionResult(
                auction_id=auction_id,
                request_id=bid_request.id,
                winning_bid=winning_bid,
                all_bids=bid_responses,
                auction_price=auction_price,
                timestamp=datetime.now()
            )
            
            # Store auction result
            auction_history[auction_id] = auction_result
            
            # Update platform statistics
            self._update_platform_stats(auction_result)
            
            # Log auction completion
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            log_rtb_step(logger, "Ad Exchange Auction Complete", {
                "auction_id": auction_id,
                "duration_ms": f"{duration_ms:.2f}",
                "total_bids": len(bid_responses),
                "winning_price": auction_price,
                "winning_campaign": winning_bid.campaign_id if winning_bid else None
            })
            
            # Send win notice to winning DSP
            if winning_bid:
                await self._send_win_notice(winning_bid, auction_price, bid_request)
            
            return auction_result
            
        except Exception as e:
            logger.error(f"Error conducting auction {auction_id}: {e}")
            # Return empty auction result on error
            return AuctionResult(
                auction_id=auction_id,
                request_id=bid_request.id,
                winning_bid=None,
                all_bids=[],
                auction_price=0.0,
                timestamp=datetime.now()
            )
    
    async def _collect_bids(self, bid_request: BidRequest) -> List[BidResponse]:
        """Collect bids from all DSPs in parallel."""
        bid_tasks = []
        
        # Create bid request tasks for each DSP
        for dsp_name, dsp_client in dsp_clients.items():
            task = asyncio.create_task(
                self._request_bid_from_dsp(dsp_client, bid_request, dsp_name)
            )
            bid_tasks.append(task)
        
        # Wait for all DSP responses with timeout
        try:
            bid_responses = await asyncio.wait_for(
                asyncio.gather(*bid_tasks, return_exceptions=True),
                timeout=self.dsp_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"DSP bid collection timeout for request {bid_request.id}")
            bid_responses = []
        
        # Filter out exceptions and None responses
        valid_bids = []
        for response in bid_responses:
            if isinstance(response, BidResponse):
                valid_bids.append(response)
            elif isinstance(response, Exception):
                logger.warning(f"DSP bid error: {response}")
        
        return valid_bids
    
    async def _request_bid_from_dsp(self, dsp_client: APIClient, bid_request: BidRequest, dsp_name: str) -> Optional[BidResponse]:
        """Request bid from a specific DSP."""
        try:
            response_data = await dsp_client.post("/bid", data=bid_request)
            bid_response = BidResponse.model_validate(response_data)
            
            log_rtb_step(logger, f"DSP Bid Received", {
                "dsp": dsp_name,
                "request_id": bid_request.id,
                "price": bid_response.price,
                "campaign_id": bid_response.campaign_id
            })
            
            return bid_response
            
        except Exception as e:
            logger.warning(f"Failed to get bid from {dsp_name}: {e}")
            return None
    
    def _evaluate_bids(self, bid_responses: List[BidResponse], bid_request: BidRequest) -> tuple[Optional[BidResponse], float]:
        """Evaluate bids and determine winner and auction price."""
        if not bid_responses:
            return None, 0.0
        
        # Filter bids that meet floor price
        valid_bids = [
            bid for bid in bid_responses 
            if bid.price >= bid_request.ad_slot.floor_price
        ]
        
        if not valid_bids:
            logger.info(f"No bids meet floor price {bid_request.ad_slot.floor_price}")
            return None, 0.0
        
        # Sort bids by price (descending)
        sorted_bids = sorted(valid_bids, key=lambda b: b.price, reverse=True)
        
        winning_bid = sorted_bids[0]
        
        # Calculate auction price
        if self.second_price_auction and len(sorted_bids) > 1:
            # Second-price auction: winner pays second-highest price + 0.01
            auction_price = sorted_bids[1].price + 0.01
        else:
            # First-price auction: winner pays their bid
            auction_price = winning_bid.price
        
        # Ensure auction price doesn't exceed winning bid
        auction_price = min(auction_price, winning_bid.price)
        
        return winning_bid, round(auction_price, 4)
    
    async def _send_win_notice(self, winning_bid: BidResponse, auction_price: float, bid_request: BidRequest):
        """Send win notice to the winning DSP."""
        try:
            win_data = {
                "campaign_id": winning_bid.campaign_id,
                "user_id": bid_request.user_id,
                "price": auction_price,
                "request_id": bid_request.id,
                "auction_id": generate_id()
            }
            
            # Send to DSP (assuming we know which DSP client to use)
            for dsp_name, dsp_client in dsp_clients.items():
                if winning_bid.dsp_id.startswith(dsp_name):
                    await dsp_client.post("/win-notice", json_data=win_data)
                    break
            
            log_rtb_step(logger, "Win Notice Sent", {
                "dsp_id": winning_bid.dsp_id,
                "campaign_id": winning_bid.campaign_id,
                "auction_price": auction_price
            })
            
        except Exception as e:
            logger.error(f"Failed to send win notice: {e}")
    
    def _update_platform_stats(self, auction_result: AuctionResult):
        """Update platform statistics."""
        platform_stats["total_auctions"] += 1
        
        if auction_result.winning_bid:
            platform_stats["successful_auctions"] += 1
            platform_fee = auction_result.auction_price * self.platform_fee_rate
            platform_stats["total_revenue"] += platform_fee
            
            # Calculate average CPM
            if platform_stats["successful_auctions"] > 0:
                platform_stats["average_cpm"] = (
                    platform_stats["total_revenue"] / platform_stats["successful_auctions"] * 1000
                )
    
    def record_transaction(self, auction_result: AuctionResult, impression_data: Dict[str, Any]):
        """Record completed transaction."""
        if not auction_result.winning_bid:
            return
        
        transaction = {
            "transaction_id": generate_id(),
            "auction_id": auction_result.auction_id,
            "campaign_id": auction_result.winning_bid.campaign_id,
            "advertiser_payment": auction_result.auction_price,
            "publisher_payment": auction_result.auction_price * (1 - self.platform_fee_rate),
            "platform_fee": auction_result.auction_price * self.platform_fee_rate,
            "timestamp": datetime.now(),
            "impression_data": impression_data
        }
        
        transaction_records.append(transaction)
        
        log_rtb_step(logger, "Transaction Recorded", {
            "transaction_id": transaction["transaction_id"],
            "advertiser_payment": transaction["advertiser_payment"],
            "publisher_payment": transaction["publisher_payment"],
            "platform_fee": transaction["platform_fee"]
        })


# Initialize auction engine
auction_engine = AdExchangeEngine()


@app.post("/rtb", response_model=AuctionResult)
async def handle_rtb_request(bid_request: BidRequest):
    """Handle real-time bidding request from SSP."""
    try:
        log_rtb_step(logger, "RTB Request Received", {
            "request_id": bid_request.id,
            "user_id": bid_request.user_id,
            "ad_slot": f"{bid_request.ad_slot.width}x{bid_request.ad_slot.height}",
            "device_type": bid_request.device.type,
            "geo": f"{bid_request.geo.city}, {bid_request.geo.country}"
        })
        
        # Conduct auction
        auction_result = await auction_engine.conduct_auction(bid_request)
        
        return auction_result
        
    except Exception as e:
        logger.error(f"Error handling RTB request: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/auction/{auction_id}", response_model=AuctionResult)
async def get_auction_details(auction_id: str):
    """Get details of a specific auction."""
    if auction_id not in auction_history:
        raise HTTPException(status_code=404, detail="Auction not found")
    
    return auction_history[auction_id]


@app.get("/stats", response_model=Dict[str, Any])
async def get_platform_stats():
    """Get Ad Exchange platform statistics."""
    recent_auctions = list(auction_history.values())[-100:]  # Last 100 auctions
    
    if recent_auctions:
        all_bids = []
        for auction in recent_auctions:
            all_bids.extend(auction.all_bids)
        
        auction_metrics = calculate_auction_metrics([bid.model_dump() for bid in all_bids])
    else:
        auction_metrics = {}
    
    stats = {
        **platform_stats,
        "recent_auction_metrics": auction_metrics,
        "success_rate": (
            platform_stats["successful_auctions"] / platform_stats["total_auctions"]
            if platform_stats["total_auctions"] > 0 else 0
        ),
        "total_transactions": len(transaction_records)
    }
    
    return stats


@app.get("/transactions", response_model=List[Dict[str, Any]])
async def get_transactions(limit: int = 100):
    """Get recent transaction records."""
    return transaction_records[-limit:]


@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint for Ad Exchange service."""
    try:
        # Check service health
        health_details = {
            "service": "ad-exchange",
            "exchange_id": auction_engine.exchange_id,
            "total_auctions": platform_stats["total_auctions"],
            "successful_auctions": platform_stats["successful_auctions"],
            "total_transactions": len(transaction_records),
            "dsp_clients_configured": len(dsp_clients),
            "workflow_stats": rtb_orchestrator.workflow_stats,
            "uptime_check": "operational",
            "timestamp": datetime.now().isoformat()
        }
        
        return create_health_response("healthy", health_details)
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        error_details = {
            "service": "ad-exchange",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
        return create_health_response("unhealthy", error_details)


class RTBWorkflowOrchestrator:
    """Complete RTB workflow orchestration engine."""
    
    def __init__(self, auction_engine: AdExchangeEngine):
        self.auction_engine = auction_engine
        self.workflow_id = generate_id()
        self.ssp_client = APIClient(config.get_service_url("ssp"))
        self.dmp_client = APIClient(config.get_service_url("dmp"))
        self.workflow_stats = {
            "total_workflows": 0,
            "successful_workflows": 0,
            "failed_workflows": 0,
            "average_duration_ms": 0.0
        }
    
    async def execute_complete_rtb_workflow(self, user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute complete RTB workflow from user visit to ad display."""
        workflow_id = generate_id()
        start_time = datetime.now()
        
        log_rtb_step(logger, "RTB Workflow Started", {
            "workflow_id": workflow_id,
            "timestamp": start_time.isoformat()
        })
        
        try:
            # Step 1: Simulate user visit and generate user context
            user_visit_data = await self._simulate_user_visit(user_context)
            
            # Step 2: Query DMP for user profile
            user_profile = await self._fetch_user_profile(user_visit_data["user_id"])
            
            # Step 3: Generate ad request from SSP
            ad_request_data = await self._generate_ad_request(user_visit_data, user_profile)
            
            # Step 4: Create bid request for auction
            bid_request = await self._create_bid_request(ad_request_data, user_profile)
            
            # Step 5: Conduct parallel DSP auction with timeout control
            auction_result = await self._conduct_parallel_auction(bid_request, user_profile)
            
            # Step 6: Process winning ad and confirm display
            display_result = await self._process_winning_ad(auction_result, user_visit_data)
            
            # Step 7: Execute data feedback loop
            feedback_result = await self._execute_feedback_loop(
                auction_result, display_result, user_visit_data, user_profile
            )
            
            # Step 8: Update statistics
            await self._update_workflow_statistics(workflow_id, start_time, True)
            
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            log_rtb_step(logger, "RTB Workflow Completed Successfully", {
                "workflow_id": workflow_id,
                "duration_ms": f"{duration_ms:.2f}",
                "winning_campaign": auction_result.winning_bid.campaign_id if auction_result.winning_bid else None,
                "final_price": auction_result.auction_price,
                "impression_confirmed": display_result.get("impression_confirmed", False)
            })
            
            return {
                "workflow_id": workflow_id,
                "status": "success",
                "duration_ms": duration_ms,
                "steps": {
                    "user_visit": user_visit_data,
                    "user_profile": user_profile.model_dump() if user_profile else None,
                    "ad_request": ad_request_data,
                    "bid_request": bid_request.model_dump(),
                    "auction_result": auction_result.model_dump(),
                    "display_result": display_result,
                    "feedback_result": feedback_result
                },
                "timestamp": datetime.now()
            }
            
        except Exception as e:
            await self._update_workflow_statistics(workflow_id, start_time, False)
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            log_rtb_step(logger, "RTB Workflow Failed", {
                "workflow_id": workflow_id,
                "duration_ms": f"{duration_ms:.2f}",
                "error": str(e)
            })
            
            return {
                "workflow_id": workflow_id,
                "status": "failed",
                "duration_ms": duration_ms,
                "error": str(e),
                "timestamp": datetime.now()
            }
    
    async def _simulate_user_visit(self, user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Simulate user visit to media page."""
        import random
        
        # Generate or use provided user context
        if user_context:
            user_id = user_context.get("user_id", f"user-{generate_id()[:8]}")
            device_type = user_context.get("device_type", "desktop")
            location = user_context.get("location", {"country": "US", "city": "San Francisco"})
        else:
            user_id = f"user-{generate_id()[:8]}"
            device_type = random.choice(["desktop", "mobile", "tablet"])
            locations = [
                {"country": "US", "city": "San Francisco", "region": "CA"},
                {"country": "US", "city": "New York", "region": "NY"},
                {"country": "US", "city": "Los Angeles", "region": "CA"},
                {"country": "UK", "city": "London", "region": "England"},
                {"country": "CA", "city": "Toronto", "region": "ON"}
            ]
            location = random.choice(locations)
        
        visit_data = {
            "user_id": user_id,
            "session_id": generate_id(),
            "device_type": device_type,
            "location": location,
            "page_url": f"https://example-publisher.com/article-{generate_id()[:6]}",
            "referrer": random.choice([
                "https://google.com/search",
                "https://facebook.com",
                "https://twitter.com",
                "direct"
            ]),
            "timestamp": datetime.now()
        }
        
        log_rtb_step(logger, "User Visit Simulated", {
            "user_id": visit_data["user_id"],
            "device_type": visit_data["device_type"],
            "location": f"{location['city']}, {location['country']}",
            "page_url": visit_data["page_url"]
        })
        
        return visit_data
    
    async def _fetch_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """Fetch user profile from DMP."""
        try:
            profile_data = await self.dmp_client.get(f"/user/{user_id}/profile")
            user_profile = UserProfile.model_validate(profile_data)
            
            log_rtb_step(logger, "User Profile Retrieved", {
                "user_id": user_id,
                "interests": len(user_profile.interests),
                "behaviors": len(user_profile.behaviors),
                "segments": len(user_profile.segments)
            })
            
            return user_profile
            
        except Exception as e:
            log_rtb_step(logger, "User Profile Not Found - Creating Default", {
                "user_id": user_id,
                "reason": str(e)
            })
            
            # Create default profile for new user
            default_profile = UserProfile(
                user_id=user_id,
                demographics={"age": 25, "gender": "unknown"},
                interests=["general"],
                behaviors=["new_visitor"],
                segments=["general_audience"]
            )
            
            # Try to create profile in DMP
            try:
                profile_data = default_profile.model_dump()
                # Convert datetime to ISO string for JSON serialization
                if 'last_updated' in profile_data:
                    profile_data['last_updated'] = profile_data['last_updated'].isoformat()
                await self.dmp_client.put(f"/user/{user_id}/profile", json_data=profile_data)
            except Exception:
                pass  # Continue even if DMP update fails
            
            return default_profile
    
    async def _generate_ad_request(self, user_visit_data: Dict[str, Any], user_profile: Optional[UserProfile]) -> Dict[str, Any]:
        """Generate ad request based on user visit and profile."""
        import random
        
        # Select ad slot based on device type and page context
        if user_visit_data["device_type"] == "mobile":
            ad_slots = [
                {"width": 320, "height": 50, "position": "top", "floor_price": 0.25},
                {"width": 300, "height": 250, "position": "inline", "floor_price": 0.30}
            ]
        else:
            ad_slots = [
                {"width": 728, "height": 90, "position": "top", "floor_price": 0.50},
                {"width": 300, "height": 250, "position": "sidebar", "floor_price": 0.35},
                {"width": 970, "height": 250, "position": "header", "floor_price": 0.60}
            ]
        
        selected_slot = random.choice(ad_slots)
        
        ad_request_data = {
            "slot_id": f"slot-{generate_id()[:8]}",
            "publisher_id": "pub-001",
            "ad_slot": selected_slot,
            "user_context": user_visit_data,
            "targeting_hints": []
        }
        
        # Add targeting hints based on user profile
        if user_profile:
            ad_request_data["targeting_hints"] = {
                "interests": user_profile.interests[:3],  # Top 3 interests
                "segments": user_profile.segments,
                "demographics": user_profile.demographics
            }
        
        log_rtb_step(logger, "Ad Request Generated", {
            "slot_id": ad_request_data["slot_id"],
            "ad_size": f"{selected_slot['width']}x{selected_slot['height']}",
            "position": selected_slot["position"],
            "floor_price": selected_slot["floor_price"],
            "targeting_hints": len(ad_request_data["targeting_hints"]) if isinstance(ad_request_data["targeting_hints"], list) else "available"
        })
        
        return ad_request_data
    
    async def _create_bid_request(self, ad_request_data: Dict[str, Any], user_profile: Optional[UserProfile]) -> BidRequest:
        """Create structured bid request for auction."""
        user_visit = ad_request_data["user_context"]
        ad_slot_data = ad_request_data["ad_slot"]
        
        bid_request = BidRequest(
            id=generate_id(),
            user_id=user_visit["user_id"],
            ad_slot=AdSlot(
                id=ad_request_data["slot_id"],
                width=ad_slot_data["width"],
                height=ad_slot_data["height"],
                position=ad_slot_data["position"],
                floor_price=ad_slot_data["floor_price"]
            ),
            device=Device(
                type=user_visit["device_type"],
                os="Unknown",
                browser="Unknown",
                ip="192.168.1.1"
            ),
            geo=Geo(
                country=user_visit["location"]["country"],
                region=user_visit["location"].get("region", "Unknown"),
                city=user_visit["location"]["city"]
            )
        )
        
        log_rtb_step(logger, "Bid Request Created", {
            "request_id": bid_request.id,
            "user_id": bid_request.user_id,
            "ad_slot": f"{bid_request.ad_slot.width}x{bid_request.ad_slot.height}",
            "floor_price": bid_request.ad_slot.floor_price,
            "geo": f"{bid_request.geo.city}, {bid_request.geo.country}"
        })
        
        return bid_request
    
    async def _conduct_parallel_auction(self, bid_request: BidRequest, user_profile: Optional[UserProfile]) -> AuctionResult:
        """Conduct parallel DSP auction with enhanced timeout control."""
        auction_start = datetime.now()
        
        log_rtb_step(logger, "Parallel Auction Started", {
            "request_id": bid_request.id,
            "dsp_count": len(dsp_clients),
            "timeout_ms": self.auction_engine.dsp_timeout * 1000
        })
        
        # Enhanced parallel bid collection with individual DSP tracking
        bid_tasks = []
        dsp_tracking = {}
        
        for dsp_name, dsp_client in dsp_clients.items():
            dsp_start_time = datetime.now()
            dsp_tracking[dsp_name] = {"start_time": dsp_start_time, "status": "pending"}
            
            task = asyncio.create_task(
                self._enhanced_dsp_bid_request(dsp_client, bid_request, dsp_name, user_profile)
            )
            bid_tasks.append((dsp_name, task))
        
        # Wait for all DSP responses with timeout
        bid_responses = []
        try:
            # Use asyncio.wait instead of gather for better timeout control
            done, pending = await asyncio.wait(
                [task for _, task in bid_tasks],
                timeout=self.auction_engine.dsp_timeout,
                return_when=asyncio.ALL_COMPLETED
            )
            
            # Process completed tasks
            for dsp_name, task in bid_tasks:
                if task in done:
                    try:
                        result = await task
                        if result:
                            bid_responses.append(result)
                            dsp_tracking[dsp_name]["status"] = "success"
                        else:
                            dsp_tracking[dsp_name]["status"] = "no_bid"
                    except Exception as e:
                        dsp_tracking[dsp_name]["status"] = f"error: {str(e)}"
                else:
                    dsp_tracking[dsp_name]["status"] = "timeout"
                    task.cancel()
            
            # Cancel any pending tasks
            for task in pending:
                task.cancel()
                
        except Exception as e:
            logger.error(f"Error in parallel auction: {e}")
            for dsp_name in dsp_tracking:
                if dsp_tracking[dsp_name]["status"] == "pending":
                    dsp_tracking[dsp_name]["status"] = f"error: {str(e)}"
        
        # Log DSP performance
        for dsp_name, tracking in dsp_tracking.items():
            duration_ms = (datetime.now() - tracking["start_time"]).total_seconds() * 1000
            log_rtb_step(logger, f"DSP {dsp_name} Response", {
                "status": tracking["status"],
                "duration_ms": f"{duration_ms:.2f}"
            })
        
        # Evaluate bids and create auction result
        winning_bid, auction_price = self.auction_engine._evaluate_bids(bid_responses, bid_request)
        
        auction_result = AuctionResult(
            auction_id=generate_id(),
            request_id=bid_request.id,
            winning_bid=winning_bid,
            all_bids=bid_responses,
            auction_price=auction_price,
            timestamp=datetime.now()
        )
        
        # Store auction result
        auction_history[auction_result.auction_id] = auction_result
        
        auction_duration = (datetime.now() - auction_start).total_seconds() * 1000
        
        log_rtb_step(logger, "Parallel Auction Completed", {
            "auction_id": auction_result.auction_id,
            "duration_ms": f"{auction_duration:.2f}",
            "total_bids": len(bid_responses),
            "winning_price": auction_price,
            "winning_campaign": winning_bid.campaign_id if winning_bid else None,
            "dsp_performance": {name: tracking["status"] for name, tracking in dsp_tracking.items()}
        })
        
        return auction_result
    
    async def _enhanced_dsp_bid_request(self, dsp_client: APIClient, bid_request: BidRequest, 
                                      dsp_name: str, user_profile: Optional[UserProfile]) -> Optional[BidResponse]:
        """Enhanced DSP bid request with user profile context."""
        try:
            # Add user profile context to bid request if available
            enhanced_request_data = bid_request.model_dump()
            if user_profile:
                enhanced_request_data["user_profile"] = user_profile.model_dump()
            
            response_data = await dsp_client.post("/bid", json_data=enhanced_request_data)
            bid_response = BidResponse.model_validate(response_data)
            
            log_rtb_step(logger, f"Enhanced DSP Bid Received", {
                "dsp": dsp_name,
                "request_id": bid_request.id,
                "price": bid_response.price,
                "campaign_id": bid_response.campaign_id,
                "user_profile_provided": user_profile is not None
            })
            
            return bid_response
            
        except Exception as e:
            logger.warning(f"Enhanced bid request failed for {dsp_name}: {e}")
            return None
    
    async def _process_winning_ad(self, auction_result: AuctionResult, user_visit_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process winning ad and simulate display confirmation."""
        if not auction_result.winning_bid:
            log_rtb_step(logger, "No Winning Ad - Display Fallback", {
                "auction_id": auction_result.auction_id,
                "fallback_type": "house_ad"
            })
            
            return {
                "impression_confirmed": False,
                "display_type": "fallback",
                "fallback_reason": "no_winning_bid",
                "impression_id": None
            }
        
        # Generate impression ID and simulate ad display
        impression_id = generate_id()
        
        # Simulate display confirmation with SSP
        try:
            impression_data = {
                "impression_id": impression_id,
                "auction_id": auction_result.auction_id,
                "campaign_id": auction_result.winning_bid.campaign_id,
                "user_id": user_visit_data["user_id"],
                "price": auction_result.auction_price,
                "creative": auction_result.winning_bid.creative,
                "timestamp": datetime.now().isoformat()
            }
            
            # Send impression confirmation to SSP
            await self.ssp_client.post("/impression", json_data=impression_data)
            
            log_rtb_step(logger, "Ad Display Confirmed", {
                "impression_id": impression_id,
                "campaign_id": auction_result.winning_bid.campaign_id,
                "price": auction_result.auction_price,
                "creative_title": auction_result.winning_bid.creative.get("title", "Unknown"),
                "user_id": user_visit_data["user_id"]
            })
            
            # Record transaction
            self.auction_engine.record_transaction(auction_result, impression_data)
            
            return {
                "impression_confirmed": True,
                "impression_id": impression_id,
                "display_type": "paid_ad",
                "campaign_id": auction_result.winning_bid.campaign_id,
                "price": auction_result.auction_price,
                "creative": auction_result.winning_bid.creative
            }
            
        except Exception as e:
            log_rtb_step(logger, "Display Confirmation Failed - Continue Flow", {
                "impression_id": impression_id,
                "error": str(e),
                "fallback_action": "record_locally"
            })
            
            # Continue flow even if SSP confirmation fails
            return {
                "impression_confirmed": False,
                "impression_id": impression_id,
                "display_type": "paid_ad",
                "campaign_id": auction_result.winning_bid.campaign_id,
                "price": auction_result.auction_price,
                "creative": auction_result.winning_bid.creative,
                "error": str(e)
            }
    
    async def _execute_feedback_loop(self, auction_result: AuctionResult, display_result: Dict[str, Any], 
                                   user_visit_data: Dict[str, Any], user_profile: Optional[UserProfile]) -> Dict[str, Any]:
        """Execute data feedback loop to update all platforms."""
        feedback_results = {
            "dmp_update": {"status": "pending"},
            "dsp_update": {"status": "pending"},
            "ssp_update": {"status": "pending"},
            "stats_update": {"status": "pending"}
        }
        
        # Update DMP with user behavior data
        try:
            behavior_event = {
                "user_id": user_visit_data["user_id"],
                "event_type": "ad_impression" if display_result.get("impression_confirmed") else "ad_request",
                "event_data": {
                    "campaign_id": auction_result.winning_bid.campaign_id if auction_result.winning_bid else None,
                    "price": auction_result.auction_price,
                    "device_type": user_visit_data["device_type"],
                    "location": user_visit_data["location"],
                    "timestamp": datetime.now().isoformat()
                }
            }
            
            await self.dmp_client.post(f"/user/{user_visit_data['user_id']}/events", json_data=behavior_event)
            feedback_results["dmp_update"] = {"status": "success", "event_type": behavior_event["event_type"]}
            
            log_rtb_step(logger, "DMP Feedback Updated", {
                "user_id": user_visit_data["user_id"],
                "event_type": behavior_event["event_type"],
                "campaign_id": behavior_event["event_data"]["campaign_id"]
            })
            
        except Exception as e:
            feedback_results["dmp_update"] = {"status": "failed", "error": str(e)}
            log_rtb_step(logger, "DMP Feedback Failed - Continue Flow", {
                "user_id": user_visit_data["user_id"],
                "error": str(e)
            })
        
        # Update DSP with campaign performance data
        if auction_result.winning_bid:
            try:
                performance_data = {
                    "campaign_id": auction_result.winning_bid.campaign_id,
                    "impression_confirmed": display_result.get("impression_confirmed", False),
                    "price": auction_result.auction_price,
                    "user_id": user_visit_data["user_id"],
                    "timestamp": datetime.now().isoformat()
                }
                
                # Send to winning DSP
                for dsp_name, dsp_client in dsp_clients.items():
                    if auction_result.winning_bid.dsp_id.startswith(dsp_name):
                        await dsp_client.post("/performance", json_data=performance_data)
                        feedback_results["dsp_update"] = {"status": "success", "dsp": dsp_name}
                        break
                
                log_rtb_step(logger, "DSP Performance Updated", {
                    "campaign_id": auction_result.winning_bid.campaign_id,
                    "impression_confirmed": display_result.get("impression_confirmed"),
                    "price": auction_result.auction_price
                })
                
            except Exception as e:
                feedback_results["dsp_update"] = {"status": "failed", "error": str(e)}
                log_rtb_step(logger, "DSP Performance Update Failed - Continue Flow", {
                    "campaign_id": auction_result.winning_bid.campaign_id,
                    "error": str(e)
                })
        
        # Update SSP with revenue data
        try:
            revenue_data = {
                "impression_id": display_result.get("impression_id"),
                "auction_id": auction_result.auction_id,
                "revenue": auction_result.auction_price * 0.9,  # 90% to publisher
                "timestamp": datetime.now().isoformat()
            }
            
            await self.ssp_client.post("/revenue", json_data=revenue_data)
            feedback_results["ssp_update"] = {"status": "success", "revenue": revenue_data["revenue"]}
            
            log_rtb_step(logger, "SSP Revenue Updated", {
                "impression_id": display_result.get("impression_id"),
                "revenue": revenue_data["revenue"]
            })
            
        except Exception as e:
            feedback_results["ssp_update"] = {"status": "failed", "error": str(e)}
            log_rtb_step(logger, "SSP Revenue Update Failed - Continue Flow", {
                "impression_id": display_result.get("impression_id"),
                "error": str(e)
            })
        
        # Update local statistics
        try:
            self._update_workflow_statistics(
                generate_id(), 
                datetime.now(), 
                display_result.get("impression_confirmed", False)
            )
            feedback_results["stats_update"] = {"status": "success"}
            
            log_rtb_step(logger, "Local Statistics Updated", {
                "impression_confirmed": display_result.get("impression_confirmed", False)
            })
            
        except Exception as e:
            feedback_results["stats_update"] = {"status": "failed", "error": str(e)}
            log_rtb_step(logger, "Statistics Update Failed - Continue Flow", {
                "error": str(e)
            })
        
        return feedback_results
    
    async def _update_workflow_statistics(self, workflow_id: str, start_time: datetime, success: bool):
        """Update workflow execution statistics."""
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        self.workflow_stats["total_workflows"] += 1
        if success:
            self.workflow_stats["successful_workflows"] += 1
        else:
            self.workflow_stats["failed_workflows"] += 1
        
        # Update average duration
        total_workflows = self.workflow_stats["total_workflows"]
        current_avg = self.workflow_stats["average_duration_ms"]
        self.workflow_stats["average_duration_ms"] = (
            (current_avg * (total_workflows - 1) + duration_ms) / total_workflows
        )


# Initialize RTB workflow orchestrator
rtb_orchestrator = RTBWorkflowOrchestrator(auction_engine)


@app.post("/demo/rtb-flow", response_model=Dict[str, Any])
async def demo_rtb_flow(user_context: Optional[Dict[str, Any]] = None):
    """
    演示完整RTB流程接口
    
    触发从用户访问到广告展示的完整实时竞价工作流程，
    包含详细的控制台日志输出和完整的流程数据响应。
    """
    try:
        log_rtb_step(logger, "RTB Demo Flow Initiated", {
            "endpoint": "/demo/rtb-flow",
            "user_context_provided": user_context is not None,
            "timestamp": datetime.now().isoformat()
        })
        
        # Execute complete RTB workflow
        workflow_result = await rtb_orchestrator.execute_complete_rtb_workflow(user_context)
        
        # Add demo-specific metadata
        demo_response = {
            "demo_info": {
                "description": "Complete RTB workflow demonstration",
                "version": "1.0",
                "execution_timestamp": datetime.now().isoformat()
            },
            "workflow_result": workflow_result,
            "console_logs_note": "Detailed step-by-step logs are output to console during execution"
        }
        
        log_rtb_step(logger, "RTB Demo Flow Completed", {
            "workflow_id": workflow_result.get("workflow_id"),
            "status": workflow_result.get("status"),
            "duration_ms": workflow_result.get("duration_ms"),
            "final_impression": workflow_result.get("steps", {}).get("display_result", {}).get("impression_confirmed", False)
        })
        
        return demo_response
        
    except Exception as e:
        error_response = {
            "demo_info": {
                "description": "Complete RTB workflow demonstration",
                "version": "1.0",
                "execution_timestamp": datetime.now().isoformat()
            },
            "workflow_result": {
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            },
            "console_logs_note": "Error details are logged to console"
        }
        
        log_rtb_step(logger, "RTB Demo Flow Failed", {
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        })
        
        return error_response


@app.post("/demo/rtb-flow-simple")
async def demo_rtb_flow_simple():
    """
    简化版RTB演示接口
    
    快速触发RTB流程演示，返回简化的响应数据。
    """
    try:
        log_rtb_step(logger, "Simple RTB Demo Started", {
            "endpoint": "/demo/rtb-flow-simple"
        })
        
        # Use default user context for simple demo
        default_context = {
            "user_id": f"demo-user-{generate_id()[:8]}",
            "device_type": "desktop",
            "location": {"country": "US", "city": "San Francisco", "region": "CA"}
        }
        
        workflow_result = await rtb_orchestrator.execute_complete_rtb_workflow(default_context)
        
        # Return simplified response
        simple_response = {
            "status": workflow_result.get("status"),
            "duration_ms": workflow_result.get("duration_ms"),
            "winning_campaign": None,
            "final_price": 0.0,
            "impression_confirmed": False
        }
        
        # Extract key information
        if workflow_result.get("status") == "success":
            steps = workflow_result.get("steps", {})
            auction_result = steps.get("auction_result", {})
            display_result = steps.get("display_result", {})
            
            if auction_result.get("winning_bid"):
                simple_response["winning_campaign"] = auction_result["winning_bid"]["campaign_id"]
                simple_response["final_price"] = auction_result.get("auction_price", 0.0)
            
            simple_response["impression_confirmed"] = display_result.get("impression_confirmed", False)
        
        log_rtb_step(logger, "Simple RTB Demo Completed", simple_response)
        
        return simple_response
        
    except Exception as e:
        error_response = {
            "status": "failed",
            "error": str(e),
            "duration_ms": 0,
            "winning_campaign": None,
            "final_price": 0.0,
            "impression_confirmed": False
        }
        
        log_rtb_step(logger, "Simple RTB Demo Failed", {
            "error": str(e)
        })
        
        return error_response


@app.get("/demo/workflow-stats")
async def get_workflow_stats():
    """
    获取RTB工作流程统计信息
    
    返回演示工作流程的执行统计数据。
    """
    stats = {
        "workflow_statistics": rtb_orchestrator.workflow_stats,
        "platform_statistics": platform_stats,
        "recent_auctions": len(auction_history),
        "total_transactions": len(transaction_records),
        "timestamp": datetime.now().isoformat()
    }
    
    log_rtb_step(logger, "Workflow Stats Retrieved", {
        "total_workflows": rtb_orchestrator.workflow_stats["total_workflows"],
        "success_rate": (
            rtb_orchestrator.workflow_stats["successful_workflows"] / 
            max(rtb_orchestrator.workflow_stats["total_workflows"], 1)
        )
    })
    
    return stats


@app.post("/demo/reset-stats")
async def reset_demo_stats():
    """
    重置演示统计数据
    
    清除所有演示相关的统计数据和历史记录。
    """
    # Reset workflow stats
    rtb_orchestrator.workflow_stats = {
        "total_workflows": 0,
        "successful_workflows": 0,
        "failed_workflows": 0,
        "average_duration_ms": 0.0
    }
    
    # Reset platform stats
    platform_stats.update({
        "total_auctions": 0,
        "successful_auctions": 0,
        "total_revenue": 0.0,
        "average_cpm": 0.0
    })
    
    # Clear histories
    auction_history.clear()
    transaction_records.clear()
    
    log_rtb_step(logger, "Demo Statistics Reset", {
        "timestamp": datetime.now().isoformat(),
        "action": "all_stats_cleared"
    })
    
    return {
        "status": "success",
        "message": "All demo statistics have been reset",
        "timestamp": datetime.now().isoformat()
    }
    
    async def _execute_feedback_loop(self, auction_result: AuctionResult, display_result: Dict[str, Any], 
                                   user_visit_data: Dict[str, Any], user_profile: Optional[UserProfile]) -> Dict[str, Any]:
        """Execute data feedback loop to update all platforms."""
        feedback_tasks = []
        feedback_results = {}
        
        # Update DMP with user behavior
        if display_result.get("impression_confirmed"):
            feedback_tasks.append(
                self._update_dmp_user_behavior(user_visit_data, auction_result, display_result)
            )
        
        # Update campaign statistics in Ad Management
        if auction_result.winning_bid:
            feedback_tasks.append(
                self._update_campaign_stats(auction_result.winning_bid.campaign_id, auction_result.auction_price)
            )
        
        # Update SSP revenue tracking
        if display_result.get("impression_confirmed"):
            feedback_tasks.append(
                self._update_ssp_revenue(display_result)
            )
        
        # Execute all feedback tasks
        try:
            feedback_responses = await asyncio.gather(*feedback_tasks, return_exceptions=True)
            
            for i, response in enumerate(feedback_responses):
                task_name = ["dmp_update", "campaign_stats", "ssp_revenue"][i] if i < 3 else f"task_{i}"
                if isinstance(response, Exception):
                    feedback_results[task_name] = {"status": "failed", "error": str(response)}
                else:
                    feedback_results[task_name] = {"status": "success", "data": response}
                    
        except Exception as e:
            logger.error(f"Error in feedback loop execution: {e}")
            feedback_results["error"] = str(e)
        
        log_rtb_step(logger, "Data Feedback Loop Completed", {
            "tasks_executed": len(feedback_tasks),
            "successful_updates": len([r for r in feedback_results.values() if r.get("status") == "success"]),
            "failed_updates": len([r for r in feedback_results.values() if r.get("status") == "failed"])
        })
        
        return feedback_results
    
    async def _update_dmp_user_behavior(self, user_visit_data: Dict[str, Any], 
                                      auction_result: AuctionResult, display_result: Dict[str, Any]) -> Dict[str, Any]:
        """Update DMP with user behavior data."""
        try:
            event_data = {
                "event_type": "view",
                "event_data": {
                    "campaign_id": auction_result.winning_bid.campaign_id if auction_result.winning_bid else None,
                    "ad_price": auction_result.auction_price,
                    "page_url": user_visit_data["page_url"],
                    "device_type": user_visit_data["device_type"],
                    "impression_id": display_result.get("impression_id")
                }
            }
            
            response = await self.dmp_client.post(
                f"/user/{user_visit_data['user_id']}/events", 
                json_data=event_data
            )
            
            return {"status": "success", "response": response}
            
        except Exception as e:
            logger.warning(f"Failed to update DMP user behavior: {e}")
            return {"status": "failed", "error": str(e)}
    
    async def _update_campaign_stats(self, campaign_id: str, spend_amount: float) -> Dict[str, Any]:
        """Update campaign statistics in Ad Management platform."""
        try:
            # This would typically call the Ad Management service
            # For now, we'll simulate the update
            stats_update = {
                "campaign_id": campaign_id,
                "impressions": 1,
                "spend": spend_amount,
                "timestamp": datetime.now()
            }
            
            # In a real implementation, this would be:
            # response = await ad_mgmt_client.post(f"/campaigns/{campaign_id}/stats", json_data=stats_update)
            
            return {"status": "success", "stats_update": stats_update}
            
        except Exception as e:
            logger.warning(f"Failed to update campaign stats: {e}")
            return {"status": "failed", "error": str(e)}
    
    async def _update_ssp_revenue(self, display_result: Dict[str, Any]) -> Dict[str, Any]:
        """Update SSP revenue tracking."""
        try:
            revenue_data = {
                "impression_id": display_result["impression_id"],
                "revenue": display_result["revenue_split"]["publisher_revenue"],
                "timestamp": display_result["display_timestamp"]
            }
            
            # This would typically call the SSP service
            # response = await self.ssp_client.post("/revenue/record", json_data=revenue_data)
            
            return {"status": "success", "revenue_data": revenue_data}
            
        except Exception as e:
            logger.warning(f"Failed to update SSP revenue: {e}")
            return {"status": "failed", "error": str(e)}
    
    async def _update_workflow_statistics(self, workflow_id: str, start_time: datetime, success: bool):
        """Update workflow execution statistics."""
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        self.workflow_stats["total_workflows"] += 1
        if success:
            self.workflow_stats["successful_workflows"] += 1
        else:
            self.workflow_stats["failed_workflows"] += 1
        
        # Update average duration
        total_successful = self.workflow_stats["successful_workflows"]
        if total_successful > 0:
            current_avg = self.workflow_stats["average_duration_ms"]
            self.workflow_stats["average_duration_ms"] = (
                (current_avg * (total_successful - 1) + duration_ms) / total_successful
            )
    
    def get_workflow_statistics(self) -> Dict[str, Any]:
        """Get workflow execution statistics."""
        success_rate = (
            self.workflow_stats["successful_workflows"] / self.workflow_stats["total_workflows"]
            if self.workflow_stats["total_workflows"] > 0 else 0
        )
        
        return {
            **self.workflow_stats,
            "success_rate": round(success_rate, 4),
            "failure_rate": round(1 - success_rate, 4)
        }


# Initialize RTB workflow orchestrator
rtb_orchestrator = RTBWorkflowOrchestrator(auction_engine)


@app.post("/demo/rtb-flow")
async def demo_rtb_flow(user_context: Optional[Dict[str, Any]] = None):
    """Demonstrate complete RTB workflow with full orchestration."""
    try:
        log_rtb_step(logger, "RTB Demo Flow Initiated", {
            "has_user_context": user_context is not None,
            "timestamp": datetime.now().isoformat()
        })
        
        # Execute complete RTB workflow
        workflow_result = await rtb_orchestrator.execute_complete_rtb_workflow(user_context)
        
        return workflow_result
        
    except Exception as e:
        logger.error(f"Error in RTB demo flow: {e}")
        raise HTTPException(status_code=500, detail="Demo flow failed")


@app.get("/workflow/stats")
async def get_workflow_statistics():
    """Get RTB workflow execution statistics."""
    return rtb_orchestrator.get_workflow_statistics()


@app.post("/rtb/complete-workflow")
async def execute_complete_rtb_workflow(user_context: Optional[Dict[str, Any]] = None):
    """
    Execute complete RTB workflow orchestration.
    Requirements 7.1-7.7: Complete RTB workflow from user visit to ad display.
    """
    try:
        log_rtb_step(logger, "Complete RTB Workflow Requested", {
            "has_user_context": user_context is not None,
            "timestamp": datetime.now().isoformat()
        })
        
        # Execute the complete workflow
        workflow_result = await rtb_orchestrator.execute_complete_rtb_workflow(user_context)
        
        return workflow_result
        
    except Exception as e:
        logger.error(f"Error executing complete RTB workflow: {e}")
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")


@app.post("/rtb/batch-workflow")
async def execute_batch_rtb_workflows(batch_size: int = 5, user_contexts: Optional[List[Dict[str, Any]]] = None):
    """
    Execute multiple RTB workflows in parallel for performance testing.
    Requirements 7.3: Parallel processing and timeout control.
    """
    try:
        log_rtb_step(logger, "Batch RTB Workflow Requested", {
            "batch_size": batch_size,
            "has_user_contexts": user_contexts is not None,
            "timestamp": datetime.now().isoformat()
        })
        
        # Create workflow tasks
        workflow_tasks = []
        for i in range(batch_size):
            user_context = user_contexts[i] if user_contexts and i < len(user_contexts) else None
            task = asyncio.create_task(
                rtb_orchestrator.execute_complete_rtb_workflow(user_context)
            )
            workflow_tasks.append(task)
        
        # Execute all workflows in parallel
        start_time = datetime.now()
        workflow_results = await asyncio.gather(*workflow_tasks, return_exceptions=True)
        total_duration = (datetime.now() - start_time).total_seconds() * 1000
        
        # Process results
        successful_workflows = []
        failed_workflows = []
        
        for i, result in enumerate(workflow_results):
            if isinstance(result, Exception):
                failed_workflows.append({
                    "workflow_index": i,
                    "error": str(result)
                })
            else:
                successful_workflows.append(result)
        
        batch_result = {
            "batch_id": generate_id(),
            "batch_size": batch_size,
            "total_duration_ms": total_duration,
            "successful_count": len(successful_workflows),
            "failed_count": len(failed_workflows),
            "success_rate": len(successful_workflows) / batch_size,
            "successful_workflows": successful_workflows,
            "failed_workflows": failed_workflows,
            "timestamp": datetime.now()
        }
        
        log_rtb_step(logger, "Batch RTB Workflow Completed", {
            "batch_id": batch_result["batch_id"],
            "successful_count": batch_result["successful_count"],
            "failed_count": batch_result["failed_count"],
            "success_rate": f"{batch_result['success_rate']:.2%}",
            "total_duration_ms": f"{total_duration:.2f}"
        })
        
        return batch_result
        
    except Exception as e:
        logger.error(f"Error executing batch RTB workflows: {e}")
        raise HTTPException(status_code=500, detail=f"Batch workflow execution failed: {str(e)}")


@app.get("/rtb/workflow-history")
async def get_workflow_history(limit: int = 50):
    """Get recent RTB workflow execution history."""
    try:
        # Get recent auction history as proxy for workflow history
        recent_auctions = list(auction_history.values())[-limit:]
        
        workflow_history = []
        for auction in recent_auctions:
            workflow_entry = {
                "auction_id": auction.auction_id,
                "request_id": auction.request_id,
                "timestamp": auction.timestamp,
                "had_winner": auction.winning_bid is not None,
                "winning_price": auction.auction_price,
                "total_bids": len(auction.all_bids),
                "winning_campaign": auction.winning_bid.campaign_id if auction.winning_bid else None
            }
            workflow_history.append(workflow_entry)
        
        return {
            "total_entries": len(workflow_history),
            "limit": limit,
            "workflow_history": workflow_history,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"Error retrieving workflow history: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve workflow history")


@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Enhanced health check endpoint."""
    try:
        # Check DSP connectivity
        dsp_health = {}
        for dsp_name, dsp_client in dsp_clients.items():
            try:
                health_result = await dsp_client.health_check()
                dsp_health[dsp_name] = health_result.get("status", "unknown")
            except Exception as e:
                dsp_health[dsp_name] = f"unhealthy: {str(e)}"
        
        # Check SSP connectivity
        ssp_healthy = True
        try:
            await ssp_client.health_check()
        except Exception:
            ssp_healthy = False
        
        # Check DMP connectivity
        dmp_healthy = True
        try:
            await dmp_client.health_check()
        except Exception:
            dmp_healthy = False
        
        # Calculate service metrics
        total_auctions = platform_stats["total_auctions"]
        successful_auctions = platform_stats["successful_auctions"]
        success_rate = successful_auctions / total_auctions if total_auctions > 0 else 0
        
        # Determine overall health
        status = "healthy"
        unhealthy_dsps = [k for k, v in dsp_health.items() if "unhealthy" in v]
        if unhealthy_dsps or not ssp_healthy or not dmp_healthy:
            status = "degraded"
        
        return HealthCheck(
            status=status,
            details={
                "service": "ad-exchange",
                "version": "0.1.0",
                "exchange_id": auction_engine.exchange_id,
                "total_auctions": total_auctions,
                "successful_auctions": successful_auctions,
                "success_rate": round(success_rate, 4),
                "average_cpm": round(platform_stats["average_cpm"], 4),
                "total_revenue": round(platform_stats["total_revenue"], 4),
                "connected_dsps": len(dsp_clients),
                "dsp_health": dsp_health,
                "dependencies": {
                    "ssp": "healthy" if ssp_healthy else "unhealthy",
                    "dmp": "healthy" if dmp_healthy else "unhealthy"
                },
                "unhealthy_dsps": unhealthy_dsps
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthCheck(
            status="unhealthy",
            details={
                "service": "ad-exchange",
                "error": str(e),
                "timestamp": datetime.now()
            }
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)