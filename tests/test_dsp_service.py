"""
Unit tests for DSP (Demand-Side Platform) service.
Tests bidding logic, campaign management, and API endpoints.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from server.dsp.main import app, bidding_engine, campaigns_db, campaign_stats, bid_history, frequency_caps
from shared.models import (
    Campaign, BidRequest, BidResponse, UserProfile, AdSlot, Device, Geo,
    CampaignStats, HealthCheck
)


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def sample_campaign():
    """Create sample campaign for testing."""
    return Campaign(
        id="test-camp-001",
        name="Test Campaign",
        advertiser_id="test-adv-001",
        budget=1000.0,
        spent=100.0,
        targeting={
            "device_types": ["mobile", "desktop"],
            "interests": ["gaming", "technology"],
            "countries": ["US", "CA"]
        },
        creative={
            "title": "Test Ad",
            "description": "Test advertisement",
            "image_url": "https://example.com/test-ad.jpg"
        },
        status="active"
    )


@pytest.fixture
def sample_bid_request_data():
    """Create sample bid request data for testing (JSON serializable)."""
    return {
        "id": "test-req-001",
        "user_id": "test-user-001",
        "ad_slot": {
            "id": "slot-001",
            "width": 300,
            "height": 250,
            "position": "banner",
            "floor_price": 0.1
        },
        "device": {
            "type": "mobile",
            "os": "iOS",
            "browser": "Safari",
            "ip": "192.168.1.1"
        },
        "geo": {
            "country": "US",
            "region": "CA",
            "city": "San Francisco"
        },
        "timestamp": "2025-08-20T13:29:15.613971"
    }


@pytest.fixture
def sample_bid_request():
    """Create sample bid request for testing."""
    return BidRequest(
        id="test-req-001",
        user_id="test-user-001",
        ad_slot=AdSlot(
            id="slot-001",
            width=300,
            height=250,
            position="banner",
            floor_price=0.1
        ),
        device=Device(
            type="mobile",
            os="iOS",
            browser="Safari",
            ip="192.168.1.1"
        ),
        geo=Geo(
            country="US",
            region="CA",
            city="San Francisco"
        )
    )


@pytest.fixture
def sample_user_profile():
    """Create sample user profile for testing."""
    return UserProfile(
        user_id="test-user-001",
        demographics={"age": 25, "gender": "M"},
        interests=["gaming", "technology", "sports"],
        behaviors=["frequent_shopper", "mobile_user"],
        segments=["tech-enthusiast", "high-income"]
    )


@pytest.fixture
def sample_campaign_data():
    """Create sample campaign data for testing (JSON serializable)."""
    return {
        "id": "test-camp-001",
        "name": "Test Campaign",
        "advertiser_id": "test-adv-001",
        "budget": 1000.0,
        "spent": 100.0,
        "targeting": {
            "device_types": ["mobile", "desktop"],
            "interests": ["gaming", "technology"],
            "countries": ["US", "CA"]
        },
        "creative": {
            "title": "Test Ad",
            "description": "Test advertisement",
            "image_url": "https://example.com/test-ad.jpg"
        },
        "status": "active",
        "created_at": "2025-08-20T13:29:15.613971",
        "updated_at": "2025-08-20T13:29:15.613971"
    }


@pytest.fixture(autouse=True)
def reset_storage():
    """Reset in-memory storage before each test."""
    campaigns_db.clear()
    campaign_stats.clear()
    bid_history.clear()
    frequency_caps.clear()
    yield
    campaigns_db.clear()
    campaign_stats.clear()
    bid_history.clear()
    frequency_caps.clear()


class TestDSPBiddingEngine:
    """Test DSP bidding engine functionality."""
    
    @pytest.mark.asyncio
    async def test_evaluate_bid_request_success(self, sample_campaign, sample_bid_request, sample_user_profile):
        """Test successful bid evaluation."""
        # Setup
        campaigns_db[sample_campaign.id] = sample_campaign
        
        with patch.object(bidding_engine, '_get_user_profile', return_value=sample_user_profile):
            # Execute
            bid_response = await bidding_engine.evaluate_bid_request(sample_bid_request)
            
            # Assert
            assert bid_response is not None
            assert bid_response.request_id == sample_bid_request.id
            assert bid_response.campaign_id == sample_campaign.id
            assert bid_response.dsp_id == bidding_engine.dsp_id
            assert bid_response.price > 0
            assert bid_response.creative == sample_campaign.creative
    
    @pytest.mark.asyncio
    async def test_evaluate_bid_request_no_matching_campaigns(self, sample_bid_request):
        """Test bid evaluation with no matching campaigns."""
        with patch.object(bidding_engine, '_get_user_profile', return_value=None):
            # Execute
            bid_response = await bidding_engine.evaluate_bid_request(sample_bid_request)
            
            # Assert
            assert bid_response is None
    
    @pytest.mark.asyncio
    async def test_evaluate_bid_request_budget_exceeded(self, sample_campaign, sample_bid_request, sample_user_profile):
        """Test bid evaluation when campaign budget is exceeded."""
        # Setup - set spent equal to budget
        sample_campaign.spent = sample_campaign.budget
        campaigns_db[sample_campaign.id] = sample_campaign
        
        with patch.object(bidding_engine, '_get_user_profile', return_value=sample_user_profile):
            # Execute
            bid_response = await bidding_engine.evaluate_bid_request(sample_bid_request)
            
            # Assert
            assert bid_response is None
    
    @pytest.mark.asyncio
    async def test_get_user_profile_success(self, sample_user_profile):
        """Test successful user profile retrieval."""
        with patch('server.dsp.main.dmp_client.get', return_value=sample_user_profile.model_dump()):
            # Execute
            profile = await bidding_engine._get_user_profile("test-user-001")
            
            # Assert
            assert profile is not None
            assert profile.user_id == sample_user_profile.user_id
            assert profile.interests == sample_user_profile.interests
    
    @pytest.mark.asyncio
    async def test_get_user_profile_failure(self):
        """Test user profile retrieval failure."""
        with patch('server.dsp.main.dmp_client.get', side_effect=Exception("DMP unavailable")):
            # Execute
            profile = await bidding_engine._get_user_profile("test-user-001")
            
            # Assert
            assert profile is None
    
    def test_find_matching_campaigns(self, sample_campaign, sample_bid_request, sample_user_profile):
        """Test finding matching campaigns."""
        # Setup
        campaigns_db[sample_campaign.id] = sample_campaign
        
        # Execute
        matching = bidding_engine._find_matching_campaigns(sample_bid_request, sample_user_profile)
        
        # Assert
        assert len(matching) == 1
        assert matching[0].id == sample_campaign.id
    
    def test_find_matching_campaigns_no_match(self, sample_campaign, sample_bid_request, sample_user_profile):
        """Test finding campaigns with no matches."""
        # Setup - modify targeting to not match
        sample_campaign.targeting["countries"] = ["UK", "FR"]  # Different from bid request
        campaigns_db[sample_campaign.id] = sample_campaign
        
        # Execute
        matching = bidding_engine._find_matching_campaigns(sample_bid_request, sample_user_profile)
        
        # Assert
        assert len(matching) == 0
    
    def test_matches_targeting_device_type(self, sample_campaign, sample_bid_request, sample_user_profile):
        """Test device type targeting match."""
        # Test positive match
        assert bidding_engine._matches_targeting(sample_campaign, sample_bid_request, sample_user_profile)
        
        # Test negative match
        sample_campaign.targeting["device_types"] = ["desktop"]
        assert not bidding_engine._matches_targeting(sample_campaign, sample_bid_request, sample_user_profile)
    
    def test_matches_targeting_geography(self, sample_campaign, sample_bid_request, sample_user_profile):
        """Test geographic targeting match."""
        # Test positive match
        assert bidding_engine._matches_targeting(sample_campaign, sample_bid_request, sample_user_profile)
        
        # Test negative match
        sample_campaign.targeting["countries"] = ["UK", "FR"]
        assert not bidding_engine._matches_targeting(sample_campaign, sample_bid_request, sample_user_profile)
    
    def test_matches_targeting_interests(self, sample_campaign, sample_bid_request, sample_user_profile):
        """Test interest targeting match."""
        # Test positive match
        assert bidding_engine._matches_targeting(sample_campaign, sample_bid_request, sample_user_profile)
        
        # Test negative match
        sample_campaign.targeting["interests"] = ["fashion", "travel"]
        assert not bidding_engine._matches_targeting(sample_campaign, sample_bid_request, sample_user_profile)
    
    def test_select_best_campaign(self, sample_bid_request, sample_user_profile):
        """Test campaign selection logic."""
        # Setup multiple campaigns
        campaign1 = Campaign(
            id="camp-001", name="Campaign 1", advertiser_id="adv-001",
            budget=1000.0, spent=500.0, status="active"
        )
        campaign2 = Campaign(
            id="camp-002", name="Campaign 2", advertiser_id="adv-002", 
            budget=2000.0, spent=100.0, status="active"
        )
        
        campaigns = [campaign1, campaign2]
        
        # Execute
        selected = bidding_engine._select_best_campaign(campaigns, sample_bid_request, sample_user_profile)
        
        # Assert - should select campaign with highest remaining budget
        assert selected.id == "camp-002"
    
    def test_check_constraints_budget(self, sample_campaign):
        """Test budget constraint checking."""
        # Test within budget
        assert bidding_engine._check_constraints(sample_campaign, "test-user-001")
        
        # Test budget exceeded
        sample_campaign.spent = sample_campaign.budget
        assert not bidding_engine._check_constraints(sample_campaign, "test-user-001")
    
    def test_check_constraints_frequency_cap(self, sample_campaign):
        """Test frequency cap constraint checking."""
        user_id = "test-user-001"
        campaign_id = sample_campaign.id
        today = datetime.now().date().isoformat()
        
        # Setup frequency cap at limit
        frequency_caps[user_id] = {campaign_id: {today: bidding_engine.default_frequency_cap}}
        
        # Execute
        result = bidding_engine._check_constraints(sample_campaign, user_id)
        
        # Assert
        assert not result
    
    def test_calculate_bid_price(self, sample_campaign, sample_bid_request, sample_user_profile):
        """Test bid price calculation."""
        # Execute
        price = bidding_engine._calculate_bid_price(sample_campaign, sample_bid_request, sample_user_profile)
        
        # Assert
        assert price >= bidding_engine.min_bid
        assert price <= bidding_engine.max_bid
        assert isinstance(price, float)
        assert round(price, 4) == price  # Check precision
    
    def test_calculate_bid_price_floor_price(self, sample_campaign, sample_bid_request, sample_user_profile):
        """Test bid price calculation with floor price."""
        # Setup high floor price
        sample_bid_request.ad_slot.floor_price = 2.0
        
        # Execute
        price = bidding_engine._calculate_bid_price(sample_campaign, sample_bid_request, sample_user_profile)
        
        # Assert - should be above floor price
        assert price > sample_bid_request.ad_slot.floor_price
    
    def test_record_win(self, sample_campaign):
        """Test recording a winning bid."""
        # Setup
        campaigns_db[sample_campaign.id] = sample_campaign
        initial_spent = sample_campaign.spent
        user_id = "test-user-001"
        price = 1.5
        
        # Execute
        bidding_engine.record_win(sample_campaign.id, user_id, price)
        
        # Assert
        assert campaigns_db[sample_campaign.id].spent == initial_spent + price
        assert sample_campaign.id in campaign_stats
        assert campaign_stats[sample_campaign.id].impressions == 1
        assert campaign_stats[sample_campaign.id].spend == price
        
        # Check frequency cap updated
        today = datetime.now().date().isoformat()
        assert frequency_caps[user_id][sample_campaign.id][today] == 1


class TestDSPAPIEndpoints:
    """Test DSP API endpoints."""
    
    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "details" in data
    
    def test_handle_bid_request_success(self, client, sample_bid_request_data, sample_campaign, sample_user_profile):
        """Test successful bid request handling."""
        # Setup
        campaigns_db[sample_campaign.id] = sample_campaign
        
        with patch.object(bidding_engine, 'evaluate_bid_request') as mock_evaluate:
            mock_bid_response = BidResponse(
                request_id=sample_bid_request_data["id"],
                price=1.25,
                creative=sample_campaign.creative,
                campaign_id=sample_campaign.id,
                dsp_id="dsp-001"
            )
            mock_evaluate.return_value = mock_bid_response
            
            # Execute
            response = client.post("/bid", json=sample_bid_request_data)
            
            # Assert
            assert response.status_code == 200
            data = response.json()
            assert data["request_id"] == sample_bid_request_data["id"]
            assert data["price"] == 1.25
            assert data["campaign_id"] == sample_campaign.id
    
    def test_handle_bid_request_no_bid(self, client, sample_bid_request_data):
        """Test bid request with no bid response."""
        with patch.object(bidding_engine, 'evaluate_bid_request', return_value=None):
            # Execute
            response = client.post("/bid", json=sample_bid_request_data)
            
            # Assert
            assert response.status_code == 204
    
    def test_get_campaigns(self, client, sample_campaign):
        """Test getting all campaigns."""
        # Setup
        campaigns_db[sample_campaign.id] = sample_campaign
        
        # Execute
        response = client.get("/campaigns")
        
        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == sample_campaign.id
    
    def test_add_campaign(self, client, sample_campaign_data):
        """Test adding a new campaign."""
        # Execute
        response = client.post("/campaigns", json=sample_campaign_data)
        
        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_campaign_data["id"]
        assert sample_campaign_data["id"] in campaigns_db
        assert sample_campaign_data["id"] in campaign_stats
    
    def test_handle_win_notice(self, client, sample_campaign):
        """Test handling win notice."""
        # Setup
        campaigns_db[sample_campaign.id] = sample_campaign
        win_data = {
            "campaign_id": sample_campaign.id,
            "user_id": "test-user-001",
            "price": 1.5
        }
        
        # Execute
        response = client.post("/win-notice", json=win_data)
        
        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
    
    def test_handle_win_notice_missing_fields(self, client):
        """Test win notice with missing fields."""
        win_data = {"campaign_id": "test-camp-001"}  # Missing user_id and price
        
        # Execute
        response = client.post("/win-notice", json=win_data)
        
        # Assert
        assert response.status_code == 400
    
    def test_get_stats(self, client, sample_campaign):
        """Test getting DSP statistics."""
        # Setup
        campaigns_db[sample_campaign.id] = sample_campaign
        campaign_stats[sample_campaign.id] = CampaignStats(campaign_id=sample_campaign.id)
        
        # Execute
        response = client.get("/stats")
        
        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "total_bid_requests" in data
        assert "total_bids_submitted" in data
        assert "bid_rate" in data
        assert "active_campaigns" in data
        assert "total_spend" in data
        assert "campaign_stats" in data
    
    def test_get_bid_history(self, client):
        """Test getting bid history."""
        # Setup
        bid_history.append({
            "request_id": "test-req-001",
            "user_id": "test-user-001",
            "timestamp": datetime.now()
        })
        
        # Execute
        response = client.get("/bid-history")
        
        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["request_id"] == "test-req-001"
    
    def test_get_campaign_stats(self, client, sample_campaign):
        """Test getting campaign statistics."""
        # Setup
        campaign_stats[sample_campaign.id] = CampaignStats(
            campaign_id=sample_campaign.id,
            impressions=100,
            clicks=10,
            spend=150.0
        )
        
        # Execute
        response = client.get(f"/campaigns/{sample_campaign.id}/stats")
        
        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["campaign_id"] == sample_campaign.id
        assert data["impressions"] == 100
        assert data["clicks"] == 10
        assert data["spend"] == 150.0
    
    def test_get_campaign_stats_not_found(self, client):
        """Test getting stats for non-existent campaign."""
        response = client.get("/campaigns/non-existent/stats")
        
        assert response.status_code == 404
    
    def test_remove_campaign(self, client, sample_campaign):
        """Test removing a campaign."""
        # Setup
        campaigns_db[sample_campaign.id] = sample_campaign
        campaign_stats[sample_campaign.id] = CampaignStats(campaign_id=sample_campaign.id)
        
        # Execute
        response = client.delete(f"/campaigns/{sample_campaign.id}")
        
        # Assert
        assert response.status_code == 200
        assert sample_campaign.id not in campaigns_db
        assert sample_campaign.id not in campaign_stats
    
    def test_remove_campaign_not_found(self, client):
        """Test removing non-existent campaign."""
        response = client.delete("/campaigns/non-existent")
        
        assert response.status_code == 404


class TestDSPIntegration:
    """Test DSP integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_full_bidding_workflow(self, client, sample_campaign, sample_bid_request_data, sample_user_profile):
        """Test complete bidding workflow."""
        # Setup
        initial_spent = sample_campaign.spent
        campaigns_db[sample_campaign.id] = sample_campaign
        
        with patch('server.dsp.main.dmp_client.get', return_value=sample_user_profile.model_dump()):
            # Execute bid request
            response = client.post("/bid", json=sample_bid_request_data)
            
            # Assert bid response
            assert response.status_code == 200
            bid_data = response.json()
            
            # Execute win notice
            win_data = {
                "campaign_id": bid_data["campaign_id"],
                "user_id": sample_bid_request_data["user_id"],
                "price": bid_data["price"]
            }
            win_response = client.post("/win-notice", json=win_data)
            
            # Assert win notice processed
            assert win_response.status_code == 200
            
            # Check campaign spend updated
            updated_campaign = campaigns_db[sample_campaign.id]
            assert updated_campaign.spent > initial_spent
            
            # Check stats updated
            stats = campaign_stats[sample_campaign.id]
            assert stats.impressions == 1
            assert stats.spend == bid_data["price"]
    
    def test_multiple_campaigns_selection(self, client, sample_bid_request_data, sample_user_profile):
        """Test campaign selection with multiple matching campaigns."""
        # Setup multiple campaigns
        campaign1 = Campaign(
            id="camp-001", name="Campaign 1", advertiser_id="adv-001",
            budget=1000.0, spent=800.0, status="active",
            targeting={"device_types": ["mobile"], "countries": ["US"]},
            creative={"title": "Campaign 1 Ad", "description": "Test ad 1"}
        )
        campaign2 = Campaign(
            id="camp-002", name="Campaign 2", advertiser_id="adv-002",
            budget=2000.0, spent=500.0, status="active", 
            targeting={"device_types": ["mobile"], "countries": ["US"]},
            creative={"title": "Campaign 2 Ad", "description": "Test ad 2"}
        )
        
        campaigns_db[campaign1.id] = campaign1
        campaigns_db[campaign2.id] = campaign2
        
        with patch('server.dsp.main.dmp_client.get', return_value=sample_user_profile.model_dump()):
            # Execute
            response = client.post("/bid", json=sample_bid_request_data)
            
            # Assert - should select campaign with higher remaining budget
            assert response.status_code == 200
            data = response.json()
            assert data["campaign_id"] == "camp-002"  # Higher remaining budget
    
    def test_frequency_cap_enforcement(self, client, sample_campaign, sample_bid_request_data, sample_user_profile):
        """Test frequency cap enforcement."""
        # Setup
        campaigns_db[sample_campaign.id] = sample_campaign
        
        # Setup frequency cap at limit
        user_id = sample_bid_request_data["user_id"]
        today = datetime.now().date().isoformat()
        frequency_caps[user_id] = {sample_campaign.id: {today: bidding_engine.default_frequency_cap}}
        
        with patch('server.dsp.main.dmp_client.get', return_value=sample_user_profile.model_dump()):
            # Execute
            response = client.post("/bid", json=sample_bid_request_data)
            
            # Assert - should not bid due to frequency cap
            assert response.status_code == 204