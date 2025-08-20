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

from server.ad_exchange.main import app, auction_engine, AdExchangeEngine
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
        initial_auctions = self.engine._AdExchangeEngine__dict__.get('platform_stats', {}).get('total_auctions', 0)
        
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
        from server.ad_exchange.main import platform_stats
        initial_total = platform_stats["total_auctions"]
        initial_successful = platform_stats["successful_auctions"]
        initial_revenue = platform_stats["total_revenue"]
        
        self.engine._update_platform_stats(auction_result)
        
        assert platform_stats["total_auctions"] == initial_total + 1
        assert platform_stats["successful_auctions"] == initial_successful + 1
        assert platform_stats["total_revenue"] == initial_revenue + (0.5 * 0.1)  # 10% platform fee
    
    def test_record_transaction(self):
        """Test transaction recording."""
        from server.ad_exchange.main import transaction_records
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
        with patch('server.ad_exchange.main.dsp_clients', {"dsp": mock_client}):
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
        from server.ad_exchange.main import auction_history, transaction_records, platform_stats
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
    
    @patch('server.ad_exchange.main.auction_engine.conduct_auction')
    def test_rtb_request_success(self, mock_conduct_auction):
        """Test successful RTB request handling."""
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
    
    @patch('server.ad_exchange.main.auction_engine.conduct_auction')
    def test_demo_rtb_flow(self, mock_conduct_auction):
        """Test RTB demo flow endpoint."""
        # Mock auction result with winning bid
        winning_bid = BidResponse(
            request_id="req-001",
            price=0.5,
            creative={"title": "Demo Ad"},
            campaign_id="camp-001",
            dsp_id="dsp-001"
        )
        
        mock_auction_result = AuctionResult(
            auction_id="auction-001",
            request_id="req-001",
            winning_bid=winning_bid,
            all_bids=[winning_bid],
            auction_price=0.45
        )
        mock_conduct_auction.return_value = mock_auction_result
        
        response = self.client.post("/demo/rtb-flow")
        
        assert response.status_code == 200
        data = response.json()
        assert "flow_id" in data
        assert "bid_request" in data
        assert "auction_result" in data
        assert "impression_data" in data
        assert data["impression_data"] is not None  # Should have impression data for winning bid


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


if __name__ == "__main__":
    pytest.main([__file__])