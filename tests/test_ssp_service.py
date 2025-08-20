"""
Unit tests for Supply-Side Platform (SSP) service.
Tests ad inventory management, revenue optimization, and reporting functionality.
"""

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import httpx

from server.ssp.main import app, ad_inventory, impressions_data, revenue_data
from shared.models import AdSlot, Device, Geo, BidResponse, AuctionResult, Impression


@pytest.fixture
def client():
    """Create test client."""
    # Clear any existing data
    ad_inventory.clear()
    impressions_data.clear()
    revenue_data.clear()
    
    # Initialize inventory for tests
    from server.ssp.main import initialize_inventory
    initialize_inventory()
    
    return TestClient(app)


@pytest.fixture
def sample_ad_request():
    """Sample ad request data."""
    return {
        "slot_id": "banner_top_1",
        "user_id": "user_123",
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
        },
        "publisher_id": "pub_001"
    }


@pytest.fixture
def sample_bid_response():
    """Sample bid response from Ad Exchange."""
    return BidResponse(
        request_id="req_123",
        price=1.50,
        creative={"title": "Test Ad", "image_url": "http://example.com/ad.jpg"},
        campaign_id="camp_123",
        dsp_id="dsp_001"
    )


@pytest.fixture
def sample_auction_result(sample_bid_response):
    """Sample auction result."""
    return AuctionResult(
        auction_id="auction_123",
        request_id="req_123",
        winning_bid=sample_bid_response,
        all_bids=[sample_bid_response],
        auction_price=1.50
    )


class TestSSPHealthCheck:
    """Test SSP health check functionality."""
    
    def test_health_check_success(self, client):
        """Test successful health check."""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "inventory_slots" in data["details"]
        assert "total_impressions" in data["details"]


class TestAdInventoryManagement:
    """Test ad inventory management functionality."""
    
    def test_get_all_inventory(self, client):
        """Test getting all inventory slots."""
        response = client.get("/inventory")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 3  # We initialize with 3 sample slots
        
        # Check structure of first inventory item
        if data:
            inventory = data[0]
            assert "slot_id" in inventory
            assert "publisher_id" in inventory
            assert "ad_slot" in inventory
            assert "available" in inventory
    
    def test_get_inventory_by_publisher(self, client):
        """Test filtering inventory by publisher."""
        response = client.get("/inventory?publisher_id=pub_001")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        
        # All returned items should belong to pub_001
        for inventory in data:
            assert inventory["publisher_id"] == "pub_001"
    
    def test_get_inventory_stats(self, client):
        """Test getting inventory statistics."""
        response = client.get("/inventory/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert "total_slots" in data
        assert "available_slots" in data
        assert "daily_impressions" in data
        assert "total_revenue" in data
        assert "average_fill_rate" in data
        
        assert data["total_slots"] >= 0
        assert data["available_slots"] >= 0
        assert data["daily_impressions"] >= 0
        assert data["total_revenue"] >= 0.0


class TestAdRequestProcessing:
    """Test ad request processing functionality."""
    
    @patch('server.ssp.main.send_to_ad_exchange')
    def test_process_ad_request_success(self, mock_send_to_exchange, client, sample_ad_request, sample_bid_response):
        """Test successful ad request processing."""
        # Mock successful Ad Exchange response
        mock_send_to_exchange.return_value = sample_bid_response
        
        response = client.post("/ad-request", json=sample_ad_request)
        assert response.status_code == 200
        
        data = response.json()
        assert "request_id" in data
        assert "creative" in data
        assert "price" in data
        assert "campaign_id" in data
        assert "impression_url" in data
        
        assert data["price"] == sample_bid_response.price
        assert data["campaign_id"] == sample_bid_response.campaign_id
        assert data["creative"] == sample_bid_response.creative
    
    def test_process_ad_request_invalid_slot(self, client, sample_ad_request):
        """Test ad request with invalid slot ID."""
        sample_ad_request["slot_id"] = "invalid_slot"
        
        response = client.post("/ad-request", json=sample_ad_request)
        assert response.status_code == 404
        assert "Ad slot not found" in response.json()["detail"]
    
    @patch('server.ssp.main.send_to_ad_exchange')
    def test_process_ad_request_no_winning_bid(self, mock_send_to_exchange, client, sample_ad_request):
        """Test ad request when no winning bid is available."""
        # Mock no winning bid
        mock_send_to_exchange.return_value = None
        
        response = client.post("/ad-request", json=sample_ad_request)
        assert response.status_code == 204
    
    def test_process_ad_request_invalid_data(self, client):
        """Test ad request with invalid data."""
        invalid_request = {
            "slot_id": "banner_top_1",
            "user_id": "",  # Invalid empty user_id
            "device": {
                "type": "invalid_type",  # Invalid device type
                "os": "Windows",
                "browser": "Chrome",
                "ip": "invalid_ip"  # Invalid IP
            }
        }
        
        response = client.post("/ad-request", json=invalid_request)
        assert response.status_code == 422  # Validation error


class TestAdExchangeCommunication:
    """Test communication with Ad Exchange."""
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_send_to_ad_exchange_success(self, mock_post, sample_auction_result):
        """Test successful communication with Ad Exchange."""
        from server.ssp.main import send_to_ad_exchange
        from shared.models import BidRequest, AdSlot, Device, Geo
        
        # Mock successful response
        from unittest.mock import Mock
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_auction_result.model_dump()
        mock_post.return_value = mock_response
        
        # Create test bid request
        bid_request = BidRequest(
            id="test_req",
            user_id="user_123",
            ad_slot=AdSlot(id="slot_1", width=728, height=90, position="top"),
            device=Device(type="desktop", os="Windows", browser="Chrome", ip="192.168.1.1"),
            geo=Geo(country="US", region="CA", city="SF")
        )
        
        result = await send_to_ad_exchange(bid_request)
        
        assert result is not None
        assert result.price == sample_auction_result.winning_bid.price
        assert result.campaign_id == sample_auction_result.winning_bid.campaign_id
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_send_to_ad_exchange_timeout(self, mock_post):
        """Test Ad Exchange communication timeout."""
        from server.ssp.main import send_to_ad_exchange
        from shared.models import BidRequest, AdSlot, Device, Geo
        
        # Mock timeout exception
        mock_post.side_effect = httpx.TimeoutException("Request timed out")
        
        bid_request = BidRequest(
            id="test_req",
            user_id="user_123",
            ad_slot=AdSlot(id="slot_1", width=728, height=90, position="top"),
            device=Device(type="desktop", os="Windows", browser="Chrome", ip="192.168.1.1"),
            geo=Geo(country="US", region="CA", city="SF")
        )
        
        result = await send_to_ad_exchange(bid_request)
        assert result is None
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_send_to_ad_exchange_error_response(self, mock_post):
        """Test Ad Exchange error response."""
        from server.ssp.main import send_to_ad_exchange
        from shared.models import BidRequest, AdSlot, Device, Geo
        
        # Mock error response
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response
        
        bid_request = BidRequest(
            id="test_req",
            user_id="user_123",
            ad_slot=AdSlot(id="slot_1", width=728, height=90, position="top"),
            device=Device(type="desktop", os="Windows", browser="Chrome", ip="192.168.1.1"),
            geo=Geo(country="US", region="CA", city="SF")
        )
        
        result = await send_to_ad_exchange(bid_request)
        assert result is None


class TestRevenueOptimization:
    """Test revenue optimization functionality."""
    
    def test_calculate_revenue(self):
        """Test revenue calculation algorithm."""
        from server.ssp.main import calculate_revenue
        
        winning_price = 2.00
        revenue = calculate_revenue(winning_price)
        
        # SSP takes 10% fee, so publisher gets 90%
        expected_revenue = winning_price * 0.90
        assert revenue == expected_revenue
        assert revenue == 1.80
    
    def test_calculate_revenue_zero_price(self):
        """Test revenue calculation with zero price."""
        from server.ssp.main import calculate_revenue
        
        revenue = calculate_revenue(0.0)
        assert revenue == 0.0
    
    def test_calculate_revenue_high_price(self):
        """Test revenue calculation with high price."""
        from server.ssp.main import calculate_revenue
        
        winning_price = 100.00
        revenue = calculate_revenue(winning_price)
        expected_revenue = winning_price * 0.90
        assert revenue == expected_revenue


class TestRevenueReporting:
    """Test revenue reporting functionality."""
    
    def test_get_revenue_report_empty(self, client):
        """Test revenue report with no data."""
        response = client.get("/revenue")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        # Should be empty initially
        assert len(data) == 0
    
    def test_get_revenue_report_with_publisher_filter(self, client):
        """Test revenue report filtered by publisher."""
        response = client.get("/revenue?publisher_id=pub_001&days=30")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
    
    def test_get_revenue_report_custom_period(self, client):
        """Test revenue report with custom time period."""
        response = client.get("/revenue?days=1")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)


class TestImpressionTracking:
    """Test impression tracking functionality."""
    
    def test_record_impression_not_found(self, client):
        """Test recording impression that doesn't exist."""
        response = client.post("/impression/nonexistent_impression")
        assert response.status_code == 404
        assert "Impression not found" in response.json()["detail"]
    
    @patch('server.ssp.main.impressions_data')
    def test_record_impression_success(self, mock_impressions, client):
        """Test successful impression recording."""
        # Add a mock impression to the data
        test_impression = Impression(
            id="test_impression",
            campaign_id="camp_123",
            user_id="user_123",
            price=1.50,
            revenue=1.35
        )
        mock_impressions.__iter__.return_value = [test_impression]
        
        response = client.post("/impression/test_impression")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "recorded"
        assert data["impression_id"] == "test_impression"


class TestDataValidation:
    """Test data validation and error handling."""
    
    def test_invalid_ad_request_missing_fields(self, client):
        """Test ad request with missing required fields."""
        invalid_request = {
            "slot_id": "banner_top_1"
            # Missing other required fields
        }
        
        response = client.post("/ad-request", json=invalid_request)
        assert response.status_code == 422
    
    def test_invalid_device_type(self, client, sample_ad_request):
        """Test ad request with invalid device type."""
        sample_ad_request["device"]["type"] = "invalid_device"
        
        response = client.post("/ad-request", json=sample_ad_request)
        assert response.status_code == 422
    
    def test_invalid_ip_address(self, client, sample_ad_request):
        """Test ad request with invalid IP address."""
        sample_ad_request["device"]["ip"] = "invalid.ip.address"
        
        response = client.post("/ad-request", json=sample_ad_request)
        assert response.status_code == 422


class TestConcurrentRequests:
    """Test handling of concurrent ad requests."""
    
    @patch('server.ssp.main.send_to_ad_exchange')
    def test_multiple_concurrent_requests(self, mock_send_to_exchange, client, sample_ad_request, sample_bid_response):
        """Test handling multiple concurrent ad requests."""
        mock_send_to_exchange.return_value = sample_bid_response
        
        # Send multiple requests
        responses = []
        for i in range(5):
            request_data = sample_ad_request.copy()
            request_data["user_id"] = f"user_{i}"
            response = client.post("/ad-request", json=request_data)
            responses.append(response)
        
        # All should succeed
        for response in responses:
            assert response.status_code == 200
            data = response.json()
            assert "request_id" in data
            assert "creative" in data


if __name__ == "__main__":
    pytest.main([__file__])