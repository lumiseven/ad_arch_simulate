"""
End-to-end tests for RTB demonstration flow.
Tests the complete RTB workflow demonstration interfaces and console output.
"""

import pytest
import asyncio
import json
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
RTBWorkflowOrchestrator = ad_exchange_main.RTBWorkflowOrchestrator
from shared.models import (
    BidRequest, BidResponse, AuctionResult, UserProfile, AdSlot, Device, Geo
)
from shared.utils import generate_id


class TestRTBDemoFlow:
    """Test cases for RTB demonstration flow endpoints."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.client = TestClient(app)
        
        # Import rtb_orchestrator after app initialization
        self.rtb_orchestrator = ad_exchange_main.rtb_orchestrator
        
        # Reset statistics for clean tests
        self.rtb_orchestrator.workflow_stats = {
            "total_workflows": 0,
            "successful_workflows": 0,
            "failed_workflows": 0,
            "average_duration_ms": 0.0
        }
    
    def test_demo_rtb_flow_simple_success(self):
        """Test simple RTB demo flow with successful execution."""
        with patch.object(self.rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
            # Mock successful workflow result
            mock_workflow.return_value = {
                "workflow_id": "test-workflow-001",
                "status": "success",
                "duration_ms": 85.5,
                "steps": {
                    "auction_result": {
                        "winning_bid": {
                            "campaign_id": "camp-001",
                            "price": 0.75
                        },
                        "auction_price": 0.65
                    },
                    "display_result": {
                        "impression_confirmed": True,
                        "impression_id": "imp-001"
                    }
                }
            }
            
            response = self.client.post("/demo/rtb-flow-simple")
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["status"] == "success"
            assert data["duration_ms"] == 85.5
            assert data["winning_campaign"] == "camp-001"
            assert data["final_price"] == 0.65
            assert data["impression_confirmed"] is True
    
    def test_demo_rtb_flow_simple_no_winner(self):
        """Test simple RTB demo flow with no winning bid."""
        with patch.object(self.rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
            # Mock workflow result with no winner
            mock_workflow.return_value = {
                "workflow_id": "test-workflow-002",
                "status": "success",
                "duration_ms": 45.2,
                "steps": {
                    "auction_result": {
                        "winning_bid": None,
                        "auction_price": 0.0
                    },
                    "display_result": {
                        "impression_confirmed": False,
                        "display_type": "fallback"
                    }
                }
            }
            
            response = self.client.post("/demo/rtb-flow-simple")
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["status"] == "success"
            assert data["duration_ms"] == 45.2
            assert data["winning_campaign"] is None
            assert data["final_price"] == 0.0
            assert data["impression_confirmed"] is False
    
    def test_demo_rtb_flow_simple_failure(self):
        """Test simple RTB demo flow with workflow failure."""
        with patch.object(self.rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
            # Mock workflow failure
            mock_workflow.side_effect = Exception("Service unavailable")
            
            response = self.client.post("/demo/rtb-flow-simple")
            
            assert response.status_code == 200  # Endpoint handles errors gracefully
            data = response.json()
            
            assert data["status"] == "failed"
            assert "Service unavailable" in data["error"]
            assert data["winning_campaign"] is None
            assert data["final_price"] == 0.0
            assert data["impression_confirmed"] is False
    
    def test_demo_rtb_flow_full_success(self):
        """Test full RTB demo flow with detailed response."""
        with patch.object(self.rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
            # Mock complete workflow result
            mock_workflow.return_value = {
                "workflow_id": "test-workflow-003",
                "status": "success",
                "duration_ms": 95.8,
                "steps": {
                    "user_visit": {
                        "user_id": "user-001",
                        "device_type": "desktop",
                        "location": {"country": "US", "city": "San Francisco"}
                    },
                    "user_profile": {
                        "user_id": "user-001",
                        "interests": ["technology", "sports"],
                        "segments": ["tech_enthusiast"]
                    },
                    "auction_result": {
                        "auction_id": "auction-001",
                        "winning_bid": {
                            "campaign_id": "camp-001",
                            "price": 0.80,
                            "creative": {"title": "Tech Product Ad"}
                        },
                        "auction_price": 0.70,
                        "all_bids": [{"price": 0.80}, {"price": 0.65}]
                    },
                    "display_result": {
                        "impression_confirmed": True,
                        "impression_id": "imp-001",
                        "campaign_id": "camp-001"
                    },
                    "feedback_result": {
                        "dmp_update": {"status": "success"},
                        "dsp_update": {"status": "success"},
                        "ssp_update": {"status": "success"}
                    }
                }
            }
            
            response = self.client.post("/demo/rtb-flow")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "demo_info" in data
            assert data["demo_info"]["description"] == "Complete RTB workflow demonstration"
            assert "workflow_result" in data
            assert data["workflow_result"]["status"] == "success"
            assert data["workflow_result"]["duration_ms"] == 95.8
            assert "console_logs_note" in data
    
    def test_demo_rtb_flow_with_custom_context(self):
        """Test RTB demo flow with custom user context."""
        custom_context = {
            "user_id": "custom-user-123",
            "device_type": "mobile",
            "location": {"country": "UK", "city": "London"}
        }
        
        with patch.object(self.rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
            mock_workflow.return_value = {
                "workflow_id": "test-workflow-004",
                "status": "success",
                "duration_ms": 78.3,
                "steps": {
                    "user_visit": custom_context,
                    "auction_result": {"winning_bid": None, "auction_price": 0.0},
                    "display_result": {"impression_confirmed": False}
                }
            }
            
            response = self.client.post("/demo/rtb-flow", json=custom_context)
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify custom context was passed to workflow
            mock_workflow.assert_called_once_with(custom_context)
            assert data["workflow_result"]["status"] == "success"
    
    def test_get_workflow_stats(self):
        """Test workflow statistics endpoint."""
        # Set some test statistics
        self.rtb_orchestrator.workflow_stats = {
            "total_workflows": 10,
            "successful_workflows": 8,
            "failed_workflows": 2,
            "average_duration_ms": 85.5
        }
        
        response = self.client.get("/demo/workflow-stats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "workflow_statistics" in data
        assert data["workflow_statistics"]["total_workflows"] == 10
        assert data["workflow_statistics"]["successful_workflows"] == 8
        assert data["workflow_statistics"]["failed_workflows"] == 2
        assert data["workflow_statistics"]["average_duration_ms"] == 85.5
        
        assert "platform_statistics" in data
        assert "recent_auctions" in data
        assert "total_transactions" in data
        assert "timestamp" in data
    
    def test_reset_demo_stats(self):
        """Test demo statistics reset endpoint."""
        # Set some initial statistics
        self.rtb_orchestrator.workflow_stats = {
            "total_workflows": 5,
            "successful_workflows": 4,
            "failed_workflows": 1,
            "average_duration_ms": 90.0
        }
        
        response = self.client.post("/demo/reset-stats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "success"
        assert "reset" in data["message"].lower()
        assert "timestamp" in data
        
        # Verify stats were reset
        assert self.rtb_orchestrator.workflow_stats["total_workflows"] == 0
        assert self.rtb_orchestrator.workflow_stats["successful_workflows"] == 0
        assert self.rtb_orchestrator.workflow_stats["failed_workflows"] == 0
        assert self.rtb_orchestrator.workflow_stats["average_duration_ms"] == 0.0


class TestRTBWorkflowOrchestrator:
    """Test cases for RTBWorkflowOrchestrator class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.orchestrator = RTBWorkflowOrchestrator(auction_engine)
    
    @pytest.mark.asyncio
    async def test_simulate_user_visit_default(self):
        """Test user visit simulation with default parameters."""
        visit_data = await self.orchestrator._simulate_user_visit()
        
        assert "user_id" in visit_data
        assert visit_data["user_id"].startswith("user-")
        assert "session_id" in visit_data
        assert "device_type" in visit_data
        assert visit_data["device_type"] in ["desktop", "mobile", "tablet"]
        assert "location" in visit_data
        assert "country" in visit_data["location"]
        assert "page_url" in visit_data
        assert "referrer" in visit_data
        assert "timestamp" in visit_data
    
    @pytest.mark.asyncio
    async def test_simulate_user_visit_custom_context(self):
        """Test user visit simulation with custom context."""
        custom_context = {
            "user_id": "custom-user-456",
            "device_type": "tablet",
            "location": {"country": "CA", "city": "Toronto", "region": "ON"}
        }
        
        visit_data = await self.orchestrator._simulate_user_visit(custom_context)
        
        assert visit_data["user_id"] == "custom-user-456"
        assert visit_data["device_type"] == "tablet"
        assert visit_data["location"]["country"] == "CA"
        assert visit_data["location"]["city"] == "Toronto"
        assert visit_data["location"]["region"] == "ON"
    
    @pytest.mark.asyncio
    async def test_fetch_user_profile_success(self):
        """Test successful user profile fetching from DMP."""
        mock_profile_data = {
            "user_id": "user-001",
            "demographics": {"age": 30, "gender": "male"},
            "interests": ["technology", "sports", "travel"],
            "behaviors": ["frequent_buyer", "mobile_user"],
            "segments": ["tech_enthusiast", "high_value"]
        }
        
        with patch.object(self.orchestrator.dmp_client, 'get') as mock_get:
            mock_get.return_value = mock_profile_data
            
            profile = await self.orchestrator._fetch_user_profile("user-001")
            
            assert profile is not None
            assert profile.user_id == "user-001"
            assert len(profile.interests) == 3
            assert "technology" in profile.interests
            assert len(profile.segments) == 2
            mock_get.assert_called_once_with("/user/user-001/profile")
    
    @pytest.mark.asyncio
    async def test_fetch_user_profile_not_found(self):
        """Test user profile fetching when user not found in DMP."""
        with patch.object(self.orchestrator.dmp_client, 'get') as mock_get:
            mock_get.side_effect = Exception("User not found")
            
            with patch.object(self.orchestrator.dmp_client, 'put') as mock_put:
                mock_put.return_value = {}
                
                profile = await self.orchestrator._fetch_user_profile("new-user-001")
                
                assert profile is not None
                assert profile.user_id == "new-user-001"
                assert profile.interests == ["general"]
                assert profile.behaviors == ["new_visitor"]
                assert profile.segments == ["general_audience"]
    
    @pytest.mark.asyncio
    async def test_generate_ad_request_mobile(self):
        """Test ad request generation for mobile device."""
        user_visit_data = {
            "user_id": "user-001",
            "device_type": "mobile",
            "location": {"country": "US", "city": "New York"}
        }
        
        user_profile = UserProfile(
            user_id="user-001",
            demographics={"age": 25},
            interests=["sports", "music"],
            behaviors=["mobile_user"],
            segments=["young_adults"]
        )
        
        ad_request = await self.orchestrator._generate_ad_request(user_visit_data, user_profile)
        
        assert "slot_id" in ad_request
        assert ad_request["publisher_id"] == "pub-001"
        assert "ad_slot" in ad_request
        
        # Mobile ad slots should be smaller
        ad_slot = ad_request["ad_slot"]
        assert ad_slot["width"] in [320, 300]
        assert ad_slot["height"] in [50, 250]
        
        assert "targeting_hints" in ad_request
        targeting_hints = ad_request["targeting_hints"]
        assert "interests" in targeting_hints
        assert "sports" in targeting_hints["interests"]
    
    @pytest.mark.asyncio
    async def test_generate_ad_request_desktop(self):
        """Test ad request generation for desktop device."""
        user_visit_data = {
            "user_id": "user-002",
            "device_type": "desktop",
            "location": {"country": "UK", "city": "London"}
        }
        
        user_profile = UserProfile(
            user_id="user-002",
            demographics={"age": 35},
            interests=["technology", "business"],
            behaviors=["frequent_visitor"],
            segments=["professionals"]
        )
        
        ad_request = await self.orchestrator._generate_ad_request(user_visit_data, user_profile)
        
        assert "slot_id" in ad_request
        assert "ad_slot" in ad_request
        
        # Desktop ad slots should be larger
        ad_slot = ad_request["ad_slot"]
        assert ad_slot["width"] in [728, 300, 970]
        assert ad_slot["height"] in [90, 250]
        
        targeting_hints = ad_request["targeting_hints"]
        assert "technology" in targeting_hints["interests"]
        assert "professionals" in targeting_hints["segments"]
    
    @pytest.mark.asyncio
    async def test_create_bid_request(self):
        """Test bid request creation from ad request data."""
        ad_request_data = {
            "slot_id": "slot-001",
            "publisher_id": "pub-001",
            "ad_slot": {
                "width": 728,
                "height": 90,
                "position": "top",
                "floor_price": 0.25
            },
            "user_context": {
                "user_id": "user-001",
                "device_type": "desktop",
                "location": {"country": "US", "city": "San Francisco", "region": "CA"}
            }
        }
        
        user_profile = UserProfile(
            user_id="user-001",
            demographics={"age": 30},
            interests=["technology"],
            behaviors=["tech_user"],
            segments=["tech_enthusiast"]
        )
        
        bid_request = await self.orchestrator._create_bid_request(ad_request_data, user_profile)
        
        assert isinstance(bid_request, BidRequest)
        assert bid_request.user_id == "user-001"
        assert bid_request.ad_slot.width == 728
        assert bid_request.ad_slot.height == 90
        assert bid_request.ad_slot.floor_price == 0.25
        assert bid_request.device.type == "desktop"
        assert bid_request.geo.country == "US"
        assert bid_request.geo.city == "San Francisco"
    
    @pytest.mark.asyncio
    async def test_process_winning_ad_success(self):
        """Test processing winning ad with successful display confirmation."""
        winning_bid = BidResponse(
            request_id="req-001",
            price=0.75,
            creative={"title": "Test Ad", "image_url": "https://example.com/ad.jpg"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        auction_result = AuctionResult(
            auction_id="auction-001",
            request_id="req-001",
            winning_bid=winning_bid,
            all_bids=[winning_bid],
            auction_price=0.65
        )
        
        user_visit_data = {
            "user_id": "user-001",
            "device_type": "desktop"
        }
        
        with patch.object(self.orchestrator.ssp_client, 'post') as mock_post:
            mock_post.return_value = {}
            
            display_result = await self.orchestrator._process_winning_ad(auction_result, user_visit_data)
            
            assert display_result["impression_confirmed"] is True
            assert display_result["display_type"] == "paid_ad"
            assert display_result["campaign_id"] == "camp-001"
            assert display_result["price"] == 0.65
            assert "impression_id" in display_result
            
            from unittest.mock import ANY
            mock_post.assert_called_once_with("/impression", json_data=ANY)
    
    @pytest.mark.asyncio
    async def test_process_winning_ad_no_winner(self):
        """Test processing when there's no winning ad."""
        auction_result = AuctionResult(
            auction_id="auction-001",
            request_id="req-001",
            winning_bid=None,
            all_bids=[],
            auction_price=0.0
        )
        
        user_visit_data = {"user_id": "user-001"}
        
        display_result = await self.orchestrator._process_winning_ad(auction_result, user_visit_data)
        
        assert display_result["impression_confirmed"] is False
        assert display_result["display_type"] == "fallback"
        assert display_result["fallback_reason"] == "no_winning_bid"
        assert display_result["impression_id"] is None
    
    @pytest.mark.asyncio
    async def test_process_winning_ad_ssp_failure(self):
        """Test processing winning ad when SSP confirmation fails."""
        winning_bid = BidResponse(
            request_id="req-001",
            price=0.50,
            creative={"title": "Test Ad"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        auction_result = AuctionResult(
            auction_id="auction-001",
            request_id="req-001",
            winning_bid=winning_bid,
            all_bids=[winning_bid],
            auction_price=0.45
        )
        
        user_visit_data = {"user_id": "user-001"}
        
        with patch.object(self.orchestrator.ssp_client, 'post') as mock_post:
            mock_post.side_effect = Exception("SSP unavailable")
            
            display_result = await self.orchestrator._process_winning_ad(auction_result, user_visit_data)
            
            # Should continue flow even with SSP failure
            assert display_result["impression_confirmed"] is False
            assert display_result["display_type"] == "paid_ad"
            assert display_result["campaign_id"] == "camp-001"
            assert "error" in display_result
    
    @pytest.mark.asyncio
    async def test_execute_feedback_loop_success(self):
        """Test successful execution of feedback loop."""
        winning_bid = BidResponse(
            request_id="req-001",
            price=0.60,
            creative={"title": "Test Ad"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        auction_result = AuctionResult(
            auction_id="auction-001",
            request_id="req-001",
            winning_bid=winning_bid,
            all_bids=[winning_bid],
            auction_price=0.55
        )
        
        display_result = {
            "impression_confirmed": True,
            "impression_id": "imp-001"
        }
        
        user_visit_data = {
            "user_id": "user-001",
            "device_type": "desktop",
            "location": {"country": "US", "city": "San Francisco"}
        }
        
        user_profile = UserProfile(
            user_id="user-001",
            demographics={"age": 30},
            interests=["technology"],
            behaviors=["tech_user"],
            segments=["tech_enthusiast"]
        )
        
        # Mock all service calls
        with patch.object(self.orchestrator.dmp_client, 'post') as mock_dmp_post, \
             patch.object(self.orchestrator.ssp_client, 'post') as mock_ssp_post:
            
            mock_dmp_post.return_value = {}
            mock_ssp_post.return_value = {}
            
            # Mock DSP client call
            with patch.object(ad_exchange_main, 'dsp_clients', {"dsp": AsyncMock()}) as mock_dsp_clients:
                mock_dsp_clients["dsp"].post.return_value = {}
                
                feedback_result = await self.orchestrator._execute_feedback_loop(
                    auction_result, display_result, user_visit_data, user_profile
                )
                
                assert feedback_result["dmp_update"]["status"] == "success"
                assert feedback_result["dsp_update"]["status"] == "success"
                assert feedback_result["ssp_update"]["status"] == "success"
                assert feedback_result["stats_update"]["status"] == "success"
    
    @pytest.mark.asyncio
    async def test_execute_feedback_loop_partial_failure(self):
        """Test feedback loop execution with partial service failures."""
        winning_bid = BidResponse(
            request_id="req-001",
            price=0.40,
            creative={"title": "Test Ad"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        auction_result = AuctionResult(
            auction_id="auction-001",
            request_id="req-001",
            winning_bid=winning_bid,
            all_bids=[winning_bid],
            auction_price=0.35
        )
        
        display_result = {"impression_confirmed": True, "impression_id": "imp-001"}
        user_visit_data = {"user_id": "user-001", "device_type": "mobile", "location": {"country": "US"}}
        user_profile = UserProfile(user_id="user-001", demographics={}, interests=[], behaviors=[], segments=[])
        
        # Mock DMP success, SSP failure
        with patch.object(self.orchestrator.dmp_client, 'post') as mock_dmp_post, \
             patch.object(self.orchestrator.ssp_client, 'post') as mock_ssp_post:
            
            mock_dmp_post.return_value = {}
            mock_ssp_post.side_effect = Exception("SSP service unavailable")
            
            with patch.object(ad_exchange_main, 'dsp_clients', {"dsp": AsyncMock()}) as mock_dsp_clients:
                mock_dsp_clients["dsp"].post.return_value = {}
                
                feedback_result = await self.orchestrator._execute_feedback_loop(
                    auction_result, display_result, user_visit_data, user_profile
                )
                
                # Should continue even with partial failures
                assert feedback_result["dmp_update"]["status"] == "success"
                assert feedback_result["dsp_update"]["status"] == "success"
                assert feedback_result["ssp_update"]["status"] == "failed"
                assert "SSP service unavailable" in feedback_result["ssp_update"]["error"]
                assert feedback_result["stats_update"]["status"] == "success"


class TestRTBDemoIntegration:
    """Integration tests for RTB demo functionality."""
    
    def setup_method(self):
        """Set up integration test fixtures."""
        self.client = TestClient(app)
    
    @pytest.mark.asyncio
    async def test_complete_rtb_workflow_integration(self):
        """Test complete RTB workflow integration with mocked services."""
        orchestrator = RTBWorkflowOrchestrator(auction_engine)
        
        # Mock all external service calls
        with patch.object(orchestrator.dmp_client, 'get') as mock_dmp_get, \
             patch.object(orchestrator.dmp_client, 'put') as mock_dmp_put, \
             patch.object(orchestrator.dmp_client, 'post') as mock_dmp_post, \
             patch.object(orchestrator.ssp_client, 'post') as mock_ssp_post:
            
            # Mock DMP responses
            mock_dmp_get.side_effect = Exception("User not found")  # Trigger default profile creation
            mock_dmp_put.return_value = {}
            mock_dmp_post.return_value = {}
            
            # Mock SSP responses
            mock_ssp_post.return_value = {}
            
            # Mock DSP responses
            mock_dsp_response = {
                "request_id": "test-req",
                "price": 0.85,
                "creative": {"title": "Integration Test Ad", "image_url": "https://example.com/ad.jpg"},
                "campaign_id": "integration-camp-001",
                "dsp_id": "dsp-001"
            }
            
            with patch.object(ad_exchange_main, 'dsp_clients') as mock_dsp_clients:
                mock_dsp_client = AsyncMock()
                mock_dsp_client.post.return_value = mock_dsp_response
                mock_dsp_clients.__getitem__.return_value = mock_dsp_client
                mock_dsp_clients.items.return_value = [("dsp", mock_dsp_client)]
                mock_dsp_clients.__len__.return_value = 1
                
                # Execute complete workflow
                result = await orchestrator.execute_complete_rtb_workflow()
                
                # Verify workflow completion
                assert result["status"] == "success"
                assert "workflow_id" in result
                assert "duration_ms" in result
                assert "steps" in result
                
                # Verify workflow steps
                steps = result["steps"]
                assert "user_visit" in steps
                assert "user_profile" in steps
                assert "ad_request" in steps
                assert "bid_request" in steps
                assert "auction_result" in steps
                assert "display_result" in steps
                assert "feedback_result" in steps
                
                # Verify auction result
                auction_result = steps["auction_result"]
                assert auction_result["winning_bid"] is not None
                assert auction_result["winning_bid"]["campaign_id"] == "integration-camp-001"
                assert auction_result["auction_price"] == 0.85  # Single bid, first-price
    
    def test_rtb_demo_error_handling_resilience(self):
        """Test RTB demo error handling and resilience."""
        rtb_orchestrator = ad_exchange_main.rtb_orchestrator
        with patch.object(rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
            # Test various error scenarios
            error_scenarios = [
                Exception("Network timeout"),
                Exception("Service unavailable"),
                Exception("Invalid response format"),
                Exception("Authentication failed")
            ]
            
            for error in error_scenarios:
                mock_workflow.side_effect = error
                
                response = self.client.post("/demo/rtb-flow-simple")
                
                # Should handle all errors gracefully
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "failed"
                assert str(error) in data["error"]
    
    def test_concurrent_rtb_demo_requests(self):
        """Test handling of concurrent RTB demo requests."""
        import threading
        import time
        
        results = []
        
        def make_request():
            rtb_orchestrator = ad_exchange_main.rtb_orchestrator
            with patch.object(rtb_orchestrator, 'execute_complete_rtb_workflow') as mock_workflow:
                mock_workflow.return_value = {
                    "workflow_id": f"concurrent-{threading.current_thread().ident}",
                    "status": "success",
                    "duration_ms": 50.0,
                    "steps": {"auction_result": {"winning_bid": None}}
                }
                
                response = self.client.post("/demo/rtb-flow-simple")
                results.append(response.json())
        
        # Create multiple concurrent requests
        threads = []
        for i in range(5):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify all requests completed successfully
        assert len(results) == 5
        for result in results:
            assert result["status"] == "success"
    
    def test_rtb_demo_statistics_accuracy(self):
        """Test accuracy of RTB demo statistics tracking."""
        # Reset statistics
        self.client.post("/demo/reset-stats")
        
        # Execute multiple demo flows by directly calling the orchestrator
        rtb_orchestrator = ad_exchange_main.rtb_orchestrator
        
        # Manually update statistics to simulate workflow execution
        from datetime import datetime, timedelta
        
        # Simulate 3 successful workflows
        for i in range(3):
            start_time = datetime.now() - timedelta(milliseconds=75)
            rtb_orchestrator._update_workflow_statistics(f"test-{i}", start_time, True)
        
        # Simulate 2 failed workflows
        for i in range(2):
            start_time = datetime.now() - timedelta(milliseconds=50)
            rtb_orchestrator._update_workflow_statistics(f"test-fail-{i}", start_time, False)
        
        # Check statistics
        response = self.client.get("/demo/workflow-stats")
        data = response.json()
        
        workflow_stats = data["workflow_statistics"]
        assert workflow_stats["total_workflows"] == 5
        assert workflow_stats["successful_workflows"] == 3
        assert workflow_stats["failed_workflows"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])