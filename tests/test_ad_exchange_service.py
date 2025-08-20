"""
Unit tests for Ad Exchange service.
Tests the core auction functionality and RTB workflow.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

# Import the Ad Exchange app and components
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import with correct directory name (hyphen, not underscore)
import importlib.util
spec = importlib.util.spec_from_file_location("ad_exchange_main", "server/ad-exchange/main.py")
ad_exchange_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ad_exchange_main)

app = ad_exchange_main.app
auction_engine = ad_exchange_main.auction_engine
AdExchangeEngine = ad_exchange_main.AdExchangeEngine
from shared.models import (
    BidRequest, BidResponse, AuctionResult, AdSlot, Device, Geo,
    HealthCheck
)
from shared.utils import generate_id


class TestAdExchangeEngine:
    """Test cases for AdExchangeEngine class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.engine = AdExchangeEngine()
        self.sample_bid_request = BidRequest(
            id="req-001",
            user_id="user-001",
            ad_slot=AdSlot(
                id="slot-001",
                width=728,
                height=90,
                position="top",
                floor_price=0.1
            ),
            device=Device(
                type="desktop",
                os="Windows",
                browser="Chrome",
                ip="192.168.1.1"
            ),
            geo=Geo(
                country="US",
                region="CA",
                city="San Francisco"
            )
        )
    
    def test_engine_initialization(self):
        """Test AdExchangeEngine initialization."""
        assert self.engine.exchange_id == "adx-001"
        assert self.engine.auction_timeout == 0.1
        assert self.engine.dsp_timeout == 0.05
        assert self.engine.platform_fee_rate == 0.1
        assert self.engine.second_price_auction is True
    
    def test_evaluate_bids_no_bids(self):
        """Test bid evaluation with no bids."""
        winning_bid, auction_price = self.engine._evaluate_bids([], self.sample_bid_request)
        
        assert winning_bid is None
        assert auction_price == 0.0
    
    def test_evaluate_bids_below_floor_price(self):
        """Test bid evaluation with bids below floor price."""
        low_bid = BidResponse(
            request_id="req-001",
            price=0.05,  # Below floor price of 0.1
            creative={"title": "Test Ad"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        winning_bid, auction_price = self.engine._evaluate_bids([low_bid], self.sample_bid_request)
        
        assert winning_bid is None
        assert auction_price == 0.0
    
    def test_evaluate_bids_single_valid_bid(self):
        """Test bid evaluation with single valid bid."""
        valid_bid = BidResponse(
            request_id="req-001",
            price=0.5,
            creative={"title": "Test Ad"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        winning_bid, auction_price = self.engine._evaluate_bids([valid_bid], self.sample_bid_request)
        
        assert winning_bid == valid_bid
        assert auction_price == 0.5  # First-price when only one bid
    
    def test_evaluate_bids_second_price_auction(self):
        """Test second-price auction with multiple bids."""
        bid1 = BidResponse(
            request_id="req-001",
            price=0.8,
            creative={"title": "High Bid Ad"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        bid2 = BidResponse(
            request_id="req-001",
            price=0.6,
            creative={"title": "Medium Bid Ad"},
            campaign_id="camp-002",
            dsp_id="dsp-002"
        )
        
        bid3 = BidResponse(
            request_id="req-001",
            price=0.4,
            creative={"title": "Low Bid Ad"},
            campaign_id="camp-003",
            dsp_id="dsp-003"
        )
        
        winning_bid, auction_price = self.engine._evaluate_bids([bid1, bid2, bid3], self.sample_bid_request)
        
        assert winning_bid == bid1  # Highest bid wins
        assert auction_price == 0.61  # Second price + 0.01
    
    def test_evaluate_bids_first_price_auction(self):
        """Test first-price auction mode."""
        self.engine.second_price_auction = False
        
        bid1 = BidResponse(
            request_id="req-001",
            price=0.8,
            creative={"title": "High Bid Ad"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        bid2 = BidResponse(
            request_id="req-001",
            price=0.6,
            creative={"title": "Medium Bid Ad"},
            campaign_id="camp-002",
            dsp_id="dsp-002"
        )
        
        winning_bid, auction_price = self.engine._evaluate_bids([bid1, bid2], self.sample_bid_request)
        
        assert winning_bid == bid1
        assert auction_price == 0.8  # Winner pays their bid
    
    def test_update_platform_stats(self):
        """Test platform statistics update."""
        # Create auction result with winning bid
        winning_bid = BidResponse(
            request_id="req-001",
            price=0.5,
            creative={"title": "Test Ad"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        auction_result = AuctionResult(
            auction_id="auction-001",
            request_id="req-001",
            winning_bid=winning_bid,
            all_bids=[winning_bid],
            auction_price=0.5
        )
        
        # Update stats
        platform_stats = ad_exchange_main.platform_stats
        initial_total = platform_stats["total_auctions"]
        initial_successful = platform_stats["successful_auctions"]
        initial_revenue = platform_stats["total_revenue"]
        
        self.engine._update_platform_stats(auction_result)
        
        assert platform_stats["total_auctions"] == initial_total + 1
        assert platform_stats["successful_auctions"] == initial_successful + 1
        assert platform_stats["total_revenue"] == initial_revenue + (0.5 * 0.1)  # 10% platform fee
    
    def test_record_transaction(self):
        """Test transaction recording."""
        transaction_records = ad_exchange_main.transaction_records
        initial_count = len(transaction_records)
        
        winning_bid = BidResponse(
            request_id="req-001",
            price=0.5,
            creative={"title": "Test Ad"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        auction_result = AuctionResult(
            auction_id="auction-001",
            request_id="req-001",
            winning_bid=winning_bid,
            all_bids=[winning_bid],
            auction_price=0.5
        )
        
        impression_data = {
            "impression_id": "imp-001",
            "user_id": "user-001"
        }
        
        self.engine.record_transaction(auction_result, impression_data)
        
        assert len(transaction_records) == initial_count + 1
        
        transaction = transaction_records[-1]
        assert transaction["auction_id"] == "auction-001"
        assert transaction["campaign_id"] == "camp-001"
        assert transaction["advertiser_payment"] == 0.5
        assert transaction["publisher_payment"] == 0.45  # 90% of auction price
        assert transaction["platform_fee"] == 0.05  # 10% of auction price
    
    @pytest.mark.asyncio
    async def test_request_bid_from_dsp_success(self):
        """Test successful bid request to DSP."""
        # Mock DSP client
        mock_client = AsyncMock()
        mock_client.post.return_value = {
            "request_id": "req-001",
            "price": 0.5,
            "creative": {"title": "Test Ad"},
            "campaign_id": "camp-001",
            "dsp_id": "dsp-001"
        }
        
        bid_response = await self.engine._request_bid_from_dsp(
            mock_client, self.sample_bid_request, "test-dsp"
        )
        
        assert bid_response is not None
        assert bid_response.price == 0.5
        assert bid_response.campaign_id == "camp-001"
        mock_client.post.assert_called_once_with("/bid", data=self.sample_bid_request)
    
    @pytest.mark.asyncio
    async def test_request_bid_from_dsp_failure(self):
        """Test failed bid request to DSP."""
        # Mock DSP client that raises exception
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("DSP unavailable")
        
        bid_response = await self.engine._request_bid_from_dsp(
            mock_client, self.sample_bid_request, "test-dsp"
        )
        
        assert bid_response is None
    
    @pytest.mark.asyncio
    async def test_send_win_notice(self):
        """Test sending win notice to DSP."""
        # Mock DSP client
        mock_client = AsyncMock()
        
        winning_bid = BidResponse(
            request_id="req-001",
            price=0.5,
            creative={"title": "Test Ad"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        # Patch the dsp_clients dictionary
        with patch.object(ad_exchange_main, 'dsp_clients', {"dsp": mock_client}):
            await self.engine._send_win_notice(winning_bid, 0.45, self.sample_bid_request)
        
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/win-notice"
        assert call_args[1]["json_data"]["campaign_id"] == "camp-001"
        assert call_args[1]["json_data"]["price"] == 0.45


class TestAdExchangeAPI:
    """Test cases for Ad Exchange API endpoints."""
    
    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)
        
        # Clear auction history and transaction records
        auction_history = ad_exchange_main.auction_history
        transaction_records = ad_exchange_main.transaction_records
        platform_stats = ad_exchange_main.platform_stats
        auction_history.clear()
        transaction_records.clear()
        platform_stats.update({
            "total_auctions": 0,
            "successful_auctions": 0,
            "total_revenue": 0.0,
            "average_cpm": 0.0
        })
    
    def test_health_check(self):
        """Test health check endpoint."""
        response = self.client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "total_auctions" in data["details"]
        assert "exchange_id" in data["details"]
    
    def test_get_platform_stats(self):
        """Test platform statistics endpoint."""
        response = self.client.get("/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert "total_auctions" in data
        assert "successful_auctions" in data
        assert "total_revenue" in data
        assert "success_rate" in data
    
    def test_get_auction_details_not_found(self):
        """Test getting auction details for non-existent auction."""
        response = self.client.get("/auction/non-existent")
        
        assert response.status_code == 404
        assert "Auction not found" in response.json()["detail"]
    
    def test_get_transactions(self):
        """Test getting transaction records."""
        response = self.client.get("/transactions")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_rtb_request_success(self):
        """Test successful RTB request handling."""
        with patch.object(ad_exchange_main.auction_engine, 'conduct_auction') as mock_conduct_auction:
            # Mock auction result
            mock_auction_result = AuctionResult(
                auction_id="auction-001",
                request_id="req-001",
                winning_bid=None,
                all_bids=[],
                auction_price=0.0
            )
            mock_conduct_auction.return_value = mock_auction_result
            
            bid_request_data = {
                "id": "req-001",
                "user_id": "user-001",
                "ad_slot": {
                    "id": "slot-001",
                    "width": 728,
                    "height": 90,
                    "position": "top",
                    "floor_price": 0.1
                },
                "device": {
                    "type": "desktop",
                    "os": "Windows",
                    "browser": "Chrome",
                    "ip": "192.168.1.1"
                },
                "geo": {
                    "country": "US",
                    "region": "CA",
                    "city": "San Francisco"
                }
            }
            
            response = self.client.post("/rtb", json=bid_request_data)
            
            assert response.status_code == 200
            data = response.json()
            assert data["auction_id"] == "auction-001"
            assert data["request_id"] == "req-001"
    
    def test_rtb_request_invalid_data(self):
        """Test RTB request with invalid data."""
        invalid_data = {
            "id": "req-001",
            # Missing required fields
        }
        
        response = self.client.post("/rtb", json=invalid_data)
        
        assert response.status_code == 422  # Validation error
    
    def test_demo_rtb_flow(self):
        """Test RTB demo flow endpoint."""
        with patch.object(ad_exchange_main.rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
            # Mock workflow result with winning bid
            mock_workflow.return_value = {
                "workflow_id": "test-workflow",
                "status": "success",
                "duration_ms": 85.0,
                "steps": {
                    "auction_result": {
                        "auction_id": "auction-001",
                        "winning_bid": {
                            "campaign_id": "camp-001",
                            "price": 0.5
                        },
                        "auction_price": 0.45
                    },
                    "display_result": {
                        "impression_confirmed": True,
                        "impression_id": "imp-001"
                    }
                }
            }
            
            response = self.client.post("/demo/rtb-flow")
            
            assert response.status_code == 200
            data = response.json()
            assert "demo_info" in data
            assert "workflow_result" in data
            assert data["workflow_result"]["status"] == "success"


class TestAdExchangeIntegration:
    """Integration tests for Ad Exchange service."""
    
    def setup_method(self):
        """Set up integration test fixtures."""
        self.client = TestClient(app)
    
    @pytest.mark.asyncio
    async def test_full_auction_workflow(self):
        """Test complete auction workflow integration."""
        # This would require running actual DSP services
        # For now, we'll test the workflow with mocked DSP responses
        
        engine = AdExchangeEngine()
        
        bid_request = BidRequest(
            id="integration-req-001",
            user_id="integration-user-001",
            ad_slot=AdSlot(
                id="slot-001",
                width=300,
                height=250,
                position="sidebar",
                floor_price=0.2
            ),
            device=Device(
                type="mobile",
                os="iOS",
                browser="Safari",
                ip="10.0.0.1"
            ),
            geo=Geo(
                country="US",
                region="NY",
                city="New York"
            )
        )
        
        # Mock DSP responses
        with patch.object(engine, '_collect_bids') as mock_collect_bids:
            mock_bids = [
                BidResponse(
                    request_id="integration-req-001",
                    price=0.8,
                    creative={"title": "Premium Ad", "image_url": "https://example.com/ad1.jpg"},
                    campaign_id="premium-camp-001",
                    dsp_id="dsp-001"
                ),
                BidResponse(
                    request_id="integration-req-001",
                    price=0.6,
                    creative={"title": "Standard Ad", "image_url": "https://example.com/ad2.jpg"},
                    campaign_id="standard-camp-002",
                    dsp_id="dsp-002"
                )
            ]
            mock_collect_bids.return_value = mock_bids
            
            # Conduct auction
            auction_result = await engine.conduct_auction(bid_request)
            
            # Verify auction result
            assert auction_result.winning_bid is not None
            assert auction_result.winning_bid.campaign_id == "premium-camp-001"
            assert auction_result.auction_price == 0.61  # Second price + 0.01
            assert len(auction_result.all_bids) == 2
    
    def test_error_handling_in_auction(self):
        """Test error handling during auction process."""
        # Test with malformed bid request
        invalid_bid_request = {
            "id": "error-test-req",
            "user_id": "",  # Invalid empty user_id
            "ad_slot": {
                "id": "slot-001",
                "width": -100,  # Invalid negative width
                "height": 250,
                "position": "top"
            }
        }
        
        response = self.client.post("/rtb", json=invalid_bid_request)
        assert response.status_code == 422  # Validation error



class TestRTBWorkflowOrchestrator:
    """Test cases for RTB Workflow Orchestrator."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.engine = AdExchangeEngine()
        self.orchestrator = ad_exchange_main.RTBWorkflowOrchestrator(self.engine)
    
    def test_orchestrator_initialization(self):
        """Test RTB workflow orchestrator initialization."""
        assert self.orchestrator.auction_engine == self.engine
        assert "total_workflows" in self.orchestrator.workflow_stats
        assert "successful_workflows" in self.orchestrator.workflow_stats
        assert "failed_workflows" in self.orchestrator.workflow_stats
        assert "average_duration_ms" in self.orchestrator.workflow_stats
    
    def test_get_workflow_statistics(self):
        """Test workflow statistics retrieval."""
        stats = self.orchestrator.get_workflow_statistics()
        
        assert "total_workflows" in stats
        assert "successful_workflows" in stats
        assert "failed_workflows" in stats
        assert "average_duration_ms" in stats
        assert "success_rate" in stats
        assert "failure_rate" in stats
        
        # Initially should be zero
        assert stats["total_workflows"] == 0
        assert stats["success_rate"] == 0
        assert stats["failure_rate"] == 1  # When total_workflows is 0, failure_rate is calculated as 1 - success_rate
    
    @pytest.mark.asyncio
    async def test_simulate_user_visit_with_context(self):
        """Test user visit simulation with provided context."""
        user_context = {
            "user_id": "test-user-123",
            "device_type": "mobile",
            "location": {"country": "US", "city": "New York", "region": "NY"}
        }
        
        visit_data = await self.orchestrator._simulate_user_visit(user_context)
        
        assert visit_data["user_id"] == "test-user-123"
        assert visit_data["device_type"] == "mobile"
        assert visit_data["location"]["country"] == "US"
        assert visit_data["location"]["city"] == "New York"
        assert "session_id" in visit_data
        assert "page_url" in visit_data
        assert "referrer" in visit_data
        assert "timestamp" in visit_data
    
    @pytest.mark.asyncio
    async def test_simulate_user_visit_without_context(self):
        """Test user visit simulation without provided context."""
        visit_data = await self.orchestrator._simulate_user_visit(None)
        
        assert visit_data["user_id"].startswith("user-")
        assert visit_data["device_type"] in ["desktop", "mobile", "tablet"]
        assert "country" in visit_data["location"]
        assert "city" in visit_data["location"]
        assert "session_id" in visit_data
        assert "page_url" in visit_data
        assert "referrer" in visit_data
        assert "timestamp" in visit_data
    
    @pytest.mark.asyncio
    async def test_generate_ad_request_mobile(self):
        """Test ad request generation for mobile device."""
        user_visit_data = {
            "user_id": "test-user",
            "device_type": "mobile",
            "location": {"country": "US", "city": "San Francisco"}
        }
        
        from shared.models import UserProfile
        
        user_profile = UserProfile(
            user_id="test-user",
            demographics={"age": 30, "gender": "male"},
            interests=["technology", "sports"],
            behaviors=["frequent_visitor"],
            segments=["tech_enthusiasts"]
        )
        
        ad_request = await self.orchestrator._generate_ad_request(user_visit_data, user_profile)
        
        assert "slot_id" in ad_request
        assert ad_request["publisher_id"] == "pub-001"
        assert "ad_slot" in ad_request
        assert ad_request["ad_slot"]["width"] in [320, 300]  # Mobile ad sizes
        assert ad_request["ad_slot"]["height"] in [50, 250]
        assert "targeting_hints" in ad_request
        assert ad_request["targeting_hints"]["interests"] == ["technology", "sports"]
    
    @pytest.mark.asyncio
    async def test_generate_ad_request_desktop(self):
        """Test ad request generation for desktop device."""
        user_visit_data = {
            "user_id": "test-user",
            "device_type": "desktop",
            "location": {"country": "US", "city": "San Francisco"}
        }
        
        ad_request = await self.orchestrator._generate_ad_request(user_visit_data, None)
        
        assert "slot_id" in ad_request
        assert ad_request["publisher_id"] == "pub-001"
        assert "ad_slot" in ad_request
        assert ad_request["ad_slot"]["width"] in [728, 300, 970]  # Desktop ad sizes
        assert ad_request["ad_slot"]["height"] in [90, 250]
        assert ad_request["targeting_hints"] == []  # No profile provided
    
    @pytest.mark.asyncio
    async def test_create_bid_request(self):
        """Test bid request creation."""
        ad_request_data = {
            "slot_id": "slot-123",
            "publisher_id": "pub-001",
            "ad_slot": {
                "width": 728,
                "height": 90,
                "position": "top",
                "floor_price": 0.5
            },
            "user_context": {
                "user_id": "test-user",
                "device_type": "desktop",
                "location": {"country": "US", "city": "San Francisco", "region": "CA"}
            }
        }
        
        bid_request = await self.orchestrator._create_bid_request(ad_request_data, None)
        
        assert isinstance(bid_request, BidRequest)
        assert bid_request.user_id == "test-user"
        assert bid_request.ad_slot.width == 728
        assert bid_request.ad_slot.height == 90
        assert bid_request.ad_slot.position == "top"
        assert bid_request.ad_slot.floor_price == 0.5
        assert bid_request.device.type == "desktop"
        assert bid_request.geo.country == "US"
        assert bid_request.geo.city == "San Francisco"
    
    @pytest.mark.asyncio
    async def test_process_winning_ad_with_winner(self):
        """Test processing winning ad when there is a winner."""
        winning_bid = BidResponse(
            request_id="req-001",
            price=0.8,
            creative={"title": "Test Ad", "image_url": "https://example.com/ad.jpg"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        auction_result = AuctionResult(
            auction_id="auction-001",
            request_id="req-001",
            winning_bid=winning_bid,
            all_bids=[winning_bid],
            auction_price=0.75
        )
        
        user_visit_data = {
            "user_id": "test-user",
            "page_url": "https://example.com/page"
        }
        
        display_result = await self.orchestrator._process_winning_ad(auction_result, user_visit_data)
        
        assert display_result["impression_confirmed"] is True
        assert "impression_id" in display_result
        assert display_result["campaign_id"] == "camp-001"
        assert display_result["final_price"] == 0.75
        assert "revenue_split" in display_result
        assert display_result["revenue_split"]["advertiser_payment"] == 0.75
        assert abs(display_result["revenue_split"]["platform_fee"] - 0.075) < 0.001  # 10% of 0.75 (floating point precision)
        assert abs(display_result["revenue_split"]["publisher_revenue"] - 0.675) < 0.001  # 90% of 0.75 (floating point precision)
    
    @pytest.mark.asyncio
    async def test_process_winning_ad_no_winner(self):
        """Test processing winning ad when there is no winner."""
        auction_result = AuctionResult(
            auction_id="auction-001",
            request_id="req-001",
            winning_bid=None,
            all_bids=[],
            auction_price=0.0
        )
        
        user_visit_data = {
            "user_id": "test-user",
            "page_url": "https://example.com/page"
        }
        
        display_result = await self.orchestrator._process_winning_ad(auction_result, user_visit_data)
        
        assert display_result["impression_confirmed"] is False
        assert display_result["reason"] == "no_winning_bid"
        assert display_result["auction_id"] == "auction-001"
    
    def test_update_workflow_statistics_success(self):
        """Test workflow statistics update for successful workflow."""
        from datetime import datetime, timedelta
        
        workflow_id = "test-workflow"
        start_time = datetime.now() - timedelta(milliseconds=100)
        
        initial_total = self.orchestrator.workflow_stats["total_workflows"]
        initial_successful = self.orchestrator.workflow_stats["successful_workflows"]
        
        self.orchestrator._update_workflow_statistics(workflow_id, start_time, True)
        
        assert self.orchestrator.workflow_stats["total_workflows"] == initial_total + 1
        assert self.orchestrator.workflow_stats["successful_workflows"] == initial_successful + 1
        assert self.orchestrator.workflow_stats["failed_workflows"] == 0
        assert self.orchestrator.workflow_stats["average_duration_ms"] > 0
    
    def test_update_workflow_statistics_failure(self):
        """Test workflow statistics update for failed workflow."""
        from datetime import datetime, timedelta
        
        workflow_id = "test-workflow"
        start_time = datetime.now() - timedelta(milliseconds=50)
        
        initial_total = self.orchestrator.workflow_stats["total_workflows"]
        initial_failed = self.orchestrator.workflow_stats["failed_workflows"]
        
        self.orchestrator._update_workflow_statistics(workflow_id, start_time, False)
        
        assert self.orchestrator.workflow_stats["total_workflows"] == initial_total + 1
        assert self.orchestrator.workflow_stats["failed_workflows"] == initial_failed + 1
        assert self.orchestrator.workflow_stats["average_duration_ms"] >= 0


class TestAdExchangeWorkflowEndpoints:
    """Test cases for Ad Exchange workflow endpoints."""
    
    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)
    
    def test_get_workflow_statistics_endpoint(self):
        """Test workflow statistics endpoint."""
        response = self.client.get("/workflow/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert "total_workflows" in data
        assert "successful_workflows" in data
        assert "failed_workflows" in data
        assert "average_duration_ms" in data
        assert "success_rate" in data
        assert "failure_rate" in data
    
    def test_execute_complete_rtb_workflow_endpoint(self):
        """Test complete RTB workflow execution endpoint."""
        with patch.object(ad_exchange_main.rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
            mock_workflow.return_value = {
                "workflow_id": "test-workflow",
                "status": "success",
                "duration_ms": 95.0,
                "steps": {
                    "user_visit": {"user_id": "test-user"},
                    "auction_result": {"auction_id": "test-auction"}
                }
            }
            
            response = self.client.post("/rtb/complete-workflow")
            
            assert response.status_code == 200
            data = response.json()
            assert data["workflow_id"] == "test-workflow"
            assert data["status"] == "success"
            assert data["duration_ms"] == 95.0
    
    def test_execute_complete_rtb_workflow_with_context(self):
        """Test complete RTB workflow execution with user context."""
        user_context = {
            "user_id": "custom-user-123",
            "device_type": "tablet",
            "location": {"country": "CA", "city": "Toronto"}
        }
        
        with patch.object(ad_exchange_main.rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
            mock_workflow.return_value = {
                "workflow_id": "test-workflow",
                "status": "success",
                "duration_ms": 85.0
            }
            
            response = self.client.post("/rtb/complete-workflow", json=user_context)
            
            assert response.status_code == 200
            mock_workflow.assert_called_once_with(user_context)
    
    def test_demo_rtb_flow_endpoint(self):
        """Test demo RTB flow endpoint."""
        with patch.object(ad_exchange_main.rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
            mock_workflow.return_value = {
                "workflow_id": "demo-workflow",
                "status": "success",
                "duration_ms": 78.0,
                "steps": {
                    "display_result": {"impression_confirmed": True}
                }
            }
            
            response = self.client.post("/demo/rtb-flow")
            
            assert response.status_code == 200
            data = response.json()
            assert "demo_info" in data
            assert "workflow_result" in data
            assert "console_logs_note" in data
            assert data["demo_info"]["description"] == "Complete RTB workflow demonstration"
            assert data["workflow_result"]["status"] == "success"
    
    def test_demo_rtb_flow_with_user_context(self):
        """Test demo RTB flow with custom user context."""
        user_context = {
            "user_id": "demo-user-456",
            "device_type": "mobile"
        }
        
        with patch.object(ad_exchange_main.rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
            mock_workflow.return_value = {
                "workflow_id": "demo-workflow",
                "status": "success",
                "duration_ms": 82.0
            }
            
            response = self.client.post("/demo/rtb-flow", json=user_context)
            
            assert response.status_code == 200
            data = response.json()
            assert "demo_info" in data
            assert "workflow_result" in data
            mock_workflow.assert_called_once_with(user_context)
    
    def test_demo_rtb_flow_error_handling(self):
        """Test demo RTB flow error handling."""
        with patch.object(ad_exchange_main.rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
            mock_workflow.side_effect = Exception("Workflow execution failed")
            
            response = self.client.post("/demo/rtb-flow")
            
            assert response.status_code == 200  # Demo endpoint returns 200 even on errors
            data = response.json()
            assert "demo_info" in data
            assert "workflow_result" in data
            assert data["workflow_result"]["status"] == "failed"
            assert "Workflow execution failed" in data["workflow_result"]["error"]


if __name__ == "__main__":
    pytest.main([__file__])