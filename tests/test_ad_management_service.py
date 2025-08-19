"""
Unit tests for Ad Management Platform service.
Tests campaign CRUD operations, budget management, and validation.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server', 'ad-management'))

import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from shared.models import Campaign, CampaignStatus, CampaignStats
from main import app, campaigns_db, campaign_stats_db


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def sample_campaign_data():
    """Sample campaign creation data."""
    return {
        "name": "Test Campaign",
        "advertiser_id": "advertiser_123",
        "budget": 1000.0,
        "targeting": {
            "age_range": {"min_age": 18, "max_age": 65},
            "gender": "all",
            "location": {"countries": ["US", "CA"]},
            "interests": ["technology", "gaming"]
        },
        "creative": {
            "title": "Amazing Product",
            "description": "Buy our amazing product now!",
            "image_url": "https://example.com/image.jpg",
            "click_url": "https://example.com/product"
        }
    }


@pytest.fixture
def setup_test_campaign(client, sample_campaign_data):
    """Create a test campaign and return its ID."""
    # Clear existing data
    campaigns_db.clear()
    campaign_stats_db.clear()
    
    response = client.post("/campaigns", json=sample_campaign_data)
    assert response.status_code == 200
    return response.json()["id"]


class TestHealthCheck:
    """Test health check endpoint."""
    
    def test_health_check(self, client):
        """Test health check returns healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "campaigns_count" in data["details"]
        assert "active_campaigns" in data["details"]


class TestCampaignCRUD:
    """Test campaign CRUD operations."""
    
    def test_create_campaign_success(self, client, sample_campaign_data):
        """Test successful campaign creation."""
        campaigns_db.clear()
        campaign_stats_db.clear()
        
        response = client.post("/campaigns", json=sample_campaign_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == sample_campaign_data["name"]
        assert data["advertiser_id"] == sample_campaign_data["advertiser_id"]
        assert data["budget"] == sample_campaign_data["budget"]
        assert data["spent"] == 0.0
        assert data["status"] == "draft"
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data
    
    def test_create_campaign_invalid_targeting(self, client, sample_campaign_data):
        """Test campaign creation with invalid targeting criteria."""
        campaigns_db.clear()
        
        # Invalid targeting format
        sample_campaign_data["targeting"] = {
            "age_range": "invalid_format"  # Should be dict with min_age/max_age
        }
        
        response = client.post("/campaigns", json=sample_campaign_data)
        assert response.status_code == 400
        assert "Invalid targeting criteria format" in response.json()["detail"]
    
    def test_create_campaign_invalid_creative(self, client, sample_campaign_data):
        """Test campaign creation with invalid creative content."""
        campaigns_db.clear()
        
        # Invalid creative format
        sample_campaign_data["creative"] = {
            "title": 123  # Should be string
        }
        
        response = client.post("/campaigns", json=sample_campaign_data)
        assert response.status_code == 400
        assert "Invalid creative content format" in response.json()["detail"]
    
    def test_get_campaign_success(self, client, setup_test_campaign):
        """Test successful campaign retrieval."""
        campaign_id = setup_test_campaign
        
        response = client.get(f"/campaigns/{campaign_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == campaign_id
        assert data["name"] == "Test Campaign"
    
    def test_get_campaign_not_found(self, client):
        """Test campaign retrieval with non-existent ID."""
        campaigns_db.clear()
        
        response = client.get("/campaigns/non_existent_id")
        assert response.status_code == 404
        assert response.json()["detail"] == "Campaign not found"
    
    def test_update_campaign_success(self, client, setup_test_campaign):
        """Test successful campaign update."""
        campaign_id = setup_test_campaign
        
        update_data = {
            "name": "Updated Campaign Name",
            "budget": 2000.0,
            "status": "active"
        }
        
        response = client.put(f"/campaigns/{campaign_id}", json=update_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == "Updated Campaign Name"
        assert data["budget"] == 2000.0
        assert data["status"] == "active"
    
    def test_update_campaign_budget_below_spent(self, client, setup_test_campaign):
        """Test campaign update with budget below spent amount."""
        campaign_id = setup_test_campaign
        
        # First, simulate some spending
        campaigns_db[campaign_id].spent = 500.0
        
        # Try to set budget below spent amount
        update_data = {"budget": 300.0}
        
        response = client.put(f"/campaigns/{campaign_id}", json=update_data)
        assert response.status_code == 400
        assert "Budget cannot be less than already spent amount" in response.json()["detail"]
    
    def test_delete_campaign_success(self, client, setup_test_campaign):
        """Test successful campaign deletion."""
        campaign_id = setup_test_campaign
        
        response = client.delete(f"/campaigns/{campaign_id}")
        assert response.status_code == 200
        assert response.json()["message"] == "Campaign deleted successfully"
        
        # Verify campaign is deleted
        response = client.get(f"/campaigns/{campaign_id}")
        assert response.status_code == 404
    
    def test_list_campaigns(self, client, sample_campaign_data):
        """Test campaign listing with filters."""
        campaigns_db.clear()
        
        # Create multiple campaigns
        campaign1_data = sample_campaign_data.copy()
        campaign1_data["name"] = "Campaign 1"
        campaign1_data["advertiser_id"] = "advertiser_1"
        
        campaign2_data = sample_campaign_data.copy()
        campaign2_data["name"] = "Campaign 2"
        campaign2_data["advertiser_id"] = "advertiser_2"
        
        client.post("/campaigns", json=campaign1_data)
        client.post("/campaigns", json=campaign2_data)
        
        # Test listing all campaigns
        response = client.get("/campaigns")
        assert response.status_code == 200
        assert len(response.json()) == 2
        
        # Test filtering by advertiser_id
        response = client.get("/campaigns?advertiser_id=advertiser_1")
        assert response.status_code == 200
        campaigns = response.json()
        assert len(campaigns) == 1
        assert campaigns[0]["advertiser_id"] == "advertiser_1"
        
        # Test filtering by status
        response = client.get("/campaigns?status=draft")
        assert response.status_code == 200
        campaigns = response.json()
        assert len(campaigns) == 2
        assert all(c["status"] == "draft" for c in campaigns)


class TestBudgetManagement:
    """Test budget management functionality."""
    
    def test_get_campaign_stats(self, client, setup_test_campaign):
        """Test campaign statistics retrieval."""
        campaign_id = setup_test_campaign
        
        response = client.get(f"/campaigns/{campaign_id}/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert data["campaign_id"] == campaign_id
        assert data["impressions"] == 0
        assert data["clicks"] == 0
        assert data["spend"] == 0.0
        assert data["ctr"] == 0.0
        assert data["cpc"] == 0.0
    
    def test_update_campaign_spend_success(self, client, setup_test_campaign):
        """Test successful campaign spend update."""
        campaign_id = setup_test_campaign
        
        spend_data = {"amount": 100.0}
        response = client.post(f"/campaigns/{campaign_id}/spend", json=spend_data)
        assert response.status_code == 200
        assert response.json()["message"] == "Campaign spend updated successfully"
        
        # Verify spend was updated
        response = client.get(f"/campaigns/{campaign_id}")
        assert response.status_code == 200
        assert response.json()["spent"] == 100.0
    
    def test_update_campaign_spend_exceeds_budget(self, client, setup_test_campaign):
        """Test campaign spend update that exceeds budget."""
        campaign_id = setup_test_campaign
        
        # Try to spend more than budget (budget is 1000.0)
        spend_data = {"amount": 1500.0}
        response = client.post(f"/campaigns/{campaign_id}/spend", json=spend_data)
        assert response.status_code == 400
        assert "Spend amount would exceed campaign budget" in response.json()["detail"]
    
    def test_update_campaign_spend_negative_amount(self, client, setup_test_campaign):
        """Test campaign spend update with negative amount."""
        campaign_id = setup_test_campaign
        
        spend_data = {"amount": -100.0}
        response = client.post(f"/campaigns/{campaign_id}/spend", json=spend_data)
        assert response.status_code == 400
        assert "Spend amount must be positive" in response.json()["detail"]
    
    def test_get_budget_status(self, client, setup_test_campaign):
        """Test budget status retrieval."""
        campaign_id = setup_test_campaign
        
        response = client.get(f"/campaigns/{campaign_id}/budget-status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["campaign_id"] == campaign_id
        assert data["total_budget"] == 1000.0
        assert data["spent"] == 0.0
        assert data["remaining"] == 1000.0
        assert data["utilization_rate"] == 0.0
        assert data["status"] == "healthy"
    
    def test_budget_status_warning_level(self, client, setup_test_campaign):
        """Test budget status at warning level."""
        campaign_id = setup_test_campaign
        
        # Set spend to 75% of budget
        campaigns_db[campaign_id].spent = 750.0
        
        response = client.get(f"/campaigns/{campaign_id}/budget-status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["utilization_rate"] == 0.75
        assert data["status"] == "warning"
    
    def test_budget_status_critical_level(self, client, setup_test_campaign):
        """Test budget status at critical level."""
        campaign_id = setup_test_campaign
        
        # Set spend to 95% of budget
        campaigns_db[campaign_id].spent = 950.0
        
        response = client.get(f"/campaigns/{campaign_id}/budget-status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["utilization_rate"] == 0.95
        assert data["status"] == "critical"


class TestTargetingValidation:
    """Test targeting criteria validation."""
    
    def test_validate_campaign_targeting_success(self, client, setup_test_campaign):
        """Test successful targeting validation."""
        campaign_id = setup_test_campaign
        
        response = client.post(f"/campaigns/{campaign_id}/validate-targeting")
        assert response.status_code == 200
        
        data = response.json()
        assert data["campaign_id"] == campaign_id
        assert data["targeting_valid"] is True
        assert "targeting_criteria" in data
    
    def test_validate_campaign_targeting_invalid(self, client, setup_test_campaign):
        """Test targeting validation with invalid criteria."""
        campaign_id = setup_test_campaign
        
        # Set invalid targeting criteria
        campaigns_db[campaign_id].targeting = {
            "age_range": "invalid_format"  # Should be dict
        }
        
        response = client.post(f"/campaigns/{campaign_id}/validate-targeting")
        assert response.status_code == 200
        
        data = response.json()
        assert data["targeting_valid"] is False


class TestPlatformStats:
    """Test platform-wide statistics."""
    
    def test_get_platform_stats(self, client, sample_campaign_data):
        """Test platform statistics retrieval."""
        campaigns_db.clear()
        
        # Create campaigns with different statuses
        campaign1_data = sample_campaign_data.copy()
        campaign1_data["name"] = "Active Campaign"
        response1 = client.post("/campaigns", json=campaign1_data)
        campaign1_id = response1.json()["id"]
        
        campaign2_data = sample_campaign_data.copy()
        campaign2_data["name"] = "Paused Campaign"
        response2 = client.post("/campaigns", json=campaign2_data)
        campaign2_id = response2.json()["id"]
        
        # Update statuses
        client.put(f"/campaigns/{campaign1_id}", json={"status": "active"})
        client.put(f"/campaigns/{campaign2_id}", json={"status": "paused"})
        
        # Add some spending
        campaigns_db[campaign1_id].spent = 200.0
        campaigns_db[campaign2_id].spent = 300.0
        
        response = client.get("/stats/summary")
        assert response.status_code == 200
        
        data = response.json()
        assert data["total_campaigns"] == 2
        assert data["active_campaigns"] == 1
        assert data["paused_campaigns"] == 1
        assert data["draft_campaigns"] == 0
        assert data["total_budget"] == 2000.0  # 1000 + 1000
        assert data["total_spent"] == 500.0   # 200 + 300
        assert data["remaining_budget"] == 1500.0
        assert data["budget_utilization"] == 0.25  # 500/2000


class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_campaign_not_found_errors(self, client):
        """Test various endpoints with non-existent campaign ID."""
        campaigns_db.clear()
        
        non_existent_id = "non_existent_campaign"
        
        # Test various endpoints
        endpoints = [
            ("GET", f"/campaigns/{non_existent_id}"),
            ("PUT", f"/campaigns/{non_existent_id}"),
            ("DELETE", f"/campaigns/{non_existent_id}"),
            ("GET", f"/campaigns/{non_existent_id}/stats"),
            ("POST", f"/campaigns/{non_existent_id}/spend"),
            ("GET", f"/campaigns/{non_existent_id}/budget-status"),
            ("POST", f"/campaigns/{non_existent_id}/validate-targeting"),
        ]
        
        for method, endpoint in endpoints:
            if method == "GET":
                response = client.get(endpoint)
            elif method == "PUT":
                response = client.put(endpoint, json={"name": "test"})
            elif method == "POST":
                response = client.post(endpoint, json={"amount": 100.0})
            elif method == "DELETE":
                response = client.delete(endpoint)
            
            assert response.status_code == 404
            assert response.json()["detail"] == "Campaign not found"
    
    def test_invalid_request_data(self, client):
        """Test campaign creation with invalid request data."""
        campaigns_db.clear()
        
        # Missing required fields
        invalid_data = {
            "name": "Test Campaign"
            # Missing advertiser_id and budget
        }
        
        response = client.post("/campaigns", json=invalid_data)
        assert response.status_code == 422  # Validation error