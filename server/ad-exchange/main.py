"""
广告交易平台 (Ad Exchange) 主应用程序

这是广告交易平台的核心服务，负责协调DSP和SSP之间的实时竞价(RTB)流程。
主要功能包括：
- 接收来自SSP的广告请求
- 向多个DSP发送竞价请求
- 评估和选择获胜的竞价
- 执行完整的RTB工作流程演示
- 记录交易数据和统计信息

技术栈：
- FastAPI: Web框架
- asyncio: 异步处理
- httpx: HTTP客户端
- Pydantic: 数据验证

端口: 8004
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
    """
    广告交易平台核心竞价引擎
    
    负责执行实时竞价(RTB)流程的核心引擎，包括：
    - 管理竞价超时控制
    - 协调多个DSP的并行竞价
    - 执行竞价评估和排序算法
    - 计算最终竞价价格
    - 发送获胜通知
    - 记录交易数据和统计信息
    """
    
    def __init__(self):
        """
        初始化广告交易引擎
        
        设置关键参数：
        - exchange_id: 交易平台唯一标识
        - auction_timeout: 总竞价超时时间(100ms)
        - dsp_timeout: 单个DSP响应超时时间(50ms)  
        - platform_fee_rate: 平台费率(10%)
        - second_price_auction: 是否使用第二价格竞价
        """
        self.exchange_id = "adx-001"
        self.auction_timeout = 0.1  # 100ms total auction timeout
        self.dsp_timeout = 0.05     # 50ms per DSP timeout
        self.platform_fee_rate = 0.1  # 10% platform fee
        self.second_price_auction = True  # Use second-price auction
    
    async def conduct_auction(self, bid_request: BidRequest) -> AuctionResult:
        """
        执行RTB竞价流程
        
        这是核心的竞价协调方法，执行完整的实时竞价流程：
        1. 生成竞价ID并记录开始时间
        2. 并行向所有DSP发送竞价请求
        3. 收集和评估所有竞价响应
        4. 选择获胜竞价并计算最终价格
        5. 发送获胜通知给获胜DSP
        6. 更新平台统计数据
        7. 记录完整的竞价结果
        
        参数:
            bid_request: 来自SSP的竞价请求，包含用户和广告位信息
            
        返回:
            AuctionResult: 完整的竞价结果，包含获胜竞价和所有参与竞价
            
        异常处理:
            - 如果竞价过程中出现错误，返回空的竞价结果
            - 所有错误都会被记录到日志中
        """
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
        """
        并行收集所有DSP的竞价响应
        
        这个方法负责：
        1. 为每个注册的DSP创建异步竞价任务
        2. 使用asyncio.gather并行执行所有竞价请求
        3. 设置严格的超时控制(50ms)
        4. 过滤掉异常和无效的响应
        5. 返回所有有效的竞价响应
        
        参数:
            bid_request: 竞价请求对象
            
        返回:
            List[BidResponse]: 所有有效的DSP竞价响应列表
            
        超时处理:
            - 如果任何DSP超时，会记录警告但不影响其他DSP
            - 超时的DSP不会参与最终的竞价评估
        """
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
        """
        评估竞价并确定获胜者和最终价格
        
        竞价评估流程：
        1. 过滤出满足底价要求的有效竞价
        2. 按竞价价格降序排序
        3. 选择最高价竞价作为获胜者
        4. 根据竞价模式计算最终价格：
           - 第二价格竞价：获胜者支付第二高价+0.01
           - 第一价格竞价：获胜者支付自己的出价
        5. 确保最终价格不超过获胜竞价
        
        参数:
            bid_responses: 所有DSP的竞价响应
            bid_request: 原始竞价请求(包含底价信息)
            
        返回:
            tuple: (获胜竞价对象, 最终竞价价格)
            - 如果没有有效竞价，返回(None, 0.0)
            
        竞价规则:
            - 必须满足广告位底价要求
            - 支持第一价格和第二价格竞价模式
            - 价格精确到4位小数
        """
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
            auction_result = await self.auction_engine.conduct_auction(bid_request)
            
            # Step 6: Process winning ad and confirm display
            display_result = await self._process_winning_ad(auction_result, user_visit_data)
            
            # Step 7: Execute data feedback loop
            feedback_result = await self._execute_feedback_loop(
                auction_result, display_result, user_visit_data, user_profile
            )
            
            # Step 8: Update statistics
            self._update_workflow_statistics(workflow_id, start_time, True)
            
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
            self._update_workflow_statistics(workflow_id, start_time, False)
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
    
    async def _process_winning_ad(self, auction_result: AuctionResult, user_visit_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process winning ad and simulate display."""
        if not auction_result.winning_bid:
            log_rtb_step(logger, "No Winning Ad", {
                "auction_id": auction_result.auction_id,
                "total_bids": len(auction_result.all_bids)
            })
            
            return {
                "impression_confirmed": False,
                "reason": "no_winning_bid",
                "auction_id": auction_result.auction_id
            }
        
        # Simulate ad display process
        impression_id = generate_id()
        display_timestamp = datetime.now()
        
        # Calculate revenue split
        advertiser_payment = auction_result.auction_price
        platform_fee = advertiser_payment * self.auction_engine.platform_fee_rate
        publisher_revenue = advertiser_payment - platform_fee
        
        display_result = {
            "impression_confirmed": True,
            "impression_id": impression_id,
            "campaign_id": auction_result.winning_bid.campaign_id,
            "creative": auction_result.winning_bid.creative,
            "final_price": auction_result.auction_price,
            "display_timestamp": display_timestamp,
            "revenue_split": {
                "advertiser_payment": advertiser_payment,
                "publisher_revenue": publisher_revenue,
                "platform_fee": platform_fee
            }
        }
        
        # Record transaction
        impression_data = {
            "impression_id": impression_id,
            "user_id": user_visit_data["user_id"],
            "display_timestamp": display_timestamp
        }
        
        self.auction_engine.record_transaction(auction_result, impression_data)
        
        log_rtb_step(logger, "Ad Display Confirmed", {
            "impression_id": impression_id,
            "campaign_id": auction_result.winning_bid.campaign_id,
            "final_price": auction_result.auction_price,
            "publisher_revenue": publisher_revenue,
            "platform_fee": platform_fee
        })
        
        return display_result
    
    async def _execute_feedback_loop(self, auction_result: AuctionResult, display_result: Dict[str, Any], 
                                   user_visit_data: Dict[str, Any], user_profile: Optional[UserProfile]) -> Dict[str, Any]:
        """Execute data feedback loop to update all platforms."""
        feedback_results = {}
        
        # Update DMP with user behavior
        if display_result.get("impression_confirmed"):
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
                
                await self.dmp_client.post(
                    f"/user/{user_visit_data['user_id']}/events", 
                    json_data=event_data
                )
                
                feedback_results["dmp_update"] = {"status": "success"}
                
            except Exception as e:
                feedback_results["dmp_update"] = {"status": "failed", "error": str(e)}
        
        log_rtb_step(logger, "Data Feedback Loop Completed", {
            "updates_attempted": len(feedback_results),
            "successful_updates": len([r for r in feedback_results.values() if r.get("status") == "success"])
        })
        
        return feedback_results
    
    def _update_workflow_statistics(self, workflow_id: str, start_time: datetime, success: bool):
        """Update workflow execution statistics."""
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        self.workflow_stats["total_workflows"] += 1
        if success:
            self.workflow_stats["successful_workflows"] += 1
        else:
            self.workflow_stats["failed_workflows"] += 1
        
        # Update average duration
        total_workflows = self.workflow_stats["total_workflows"]
        if total_workflows > 0:
            current_avg = self.workflow_stats["average_duration_ms"]
            self.workflow_stats["average_duration_ms"] = (
                (current_avg * (total_workflows - 1) + duration_ms) / total_workflows
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)