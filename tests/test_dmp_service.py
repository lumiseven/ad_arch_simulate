"""
Unit tests for the Data Management Platform (DMP) service.
"""

import pytest
import json
from datetime import datetime
from fastapi.testclient import TestClient
from unittest.mock import patch

from server.dmp.main import app, user_profiles, user_events, user_segments
from shared.models import UserProfile, UserEvent


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def sample_user_profile():
    """Sample user profile for testing."""
    return {
        "demographics": {"age": 25, "gender": "male", "location": "Beijing"},
        "interests": ["technology", "sports"],
        "behaviors": ["clicker", "viewer"],
        "segments": ["young_adults"]
    }


@pytest.fixture
def sample_user_event():
    """Sample user event for testing."""
    return {
        "event_type": "click",
        "event_data": {
            "category": "electronics",
            "product_id": "phone_123",
            "device_type": "mobile"
        }
    }


@pytest.fixture(autouse=True)
def clear_storage():
    """Clear in-memory storage before each test."""
    user_profiles.clear()
    user_events.clear()
    # Reset segments to default state
    user_segments.clear()
    user_segments.update({
        "high_value": [],
        "frequent_buyers": [],
        "mobile_users": [],
        "young_adults": [],
        "tech_enthusiasts": []
    })


class TestHealthCheck:
    """Test health check endpoint."""
    
    def test_health_check_success(self, client):
        """Test successful health check."""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "details" in data
        assert "total_profiles" in data["details"]
        assert "total_events" in data["details"]
        assert "segments" in data["details"]


class TestUserProfile:
    """Test user profile management."""
    
    def test_get_user_profile_not_found(self, client):
        """Test getting non-existent user profile."""
        response = client.get("/user/nonexistent/profile")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_update_user_profile_new_user(self, client, sample_user_profile):
        """Test creating new user profile."""
        user_id = "test_user_1"
        response = client.put(f"/user/{user_id}/profile", json=sample_user_profile)
        
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == user_id
        assert data["demographics"] == sample_user_profile["demographics"]
        assert set(data["interests"]) == set(sample_user_profile["interests"])
        assert set(data["behaviors"]) == set(sample_user_profile["behaviors"])
        assert "last_updated" in data
    
    def test_update_user_profile_existing_user(self, client, sample_user_profile):
        """Test updating existing user profile."""
        user_id = "test_user_2"
        
        # Create initial profile
        client.put(f"/user/{user_id}/profile", json=sample_user_profile)
        
        # Update profile
        update_data = {
            "demographics": {"age": 26, "income": "high"},
            "interests": ["gaming"],
            "behaviors": ["buyer"]
        }
        response = client.put(f"/user/{user_id}/profile", json=update_data)
        
        assert response.status_code == 200
        data = response.json()
        
        # Check merged data
        assert data["demographics"]["age"] == 26  # Updated
        assert data["demographics"]["gender"] == "male"  # Preserved
        assert data["demographics"]["income"] == "high"  # Added
        assert "technology" in data["interests"]  # Preserved
        assert "gaming" in data["interests"]  # Added
        assert "clicker" in data["behaviors"]  # Preserved
        assert "buyer" in data["behaviors"]  # Added
    
    def test_get_user_profile_success(self, client, sample_user_profile):
        """Test getting existing user profile."""
        user_id = "test_user_3"
        
        # Create profile
        client.put(f"/user/{user_id}/profile", json=sample_user_profile)
        
        # Get profile
        response = client.get(f"/user/{user_id}/profile")
        assert response.status_code == 200
        
        data = response.json()
        assert data["user_id"] == user_id
        assert data["demographics"] == sample_user_profile["demographics"]
    
    def test_update_user_profile_invalid_data(self, client):
        """Test updating user profile with invalid data."""
        user_id = "test_user_4"
        invalid_data = {
            "interests": ["", "valid_interest"],  # Empty string should be invalid
        }
        
        response = client.put(f"/user/{user_id}/profile", json=invalid_data)
        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()


class TestUserEvents:
    """Test user event recording and retrieval."""
    
    def test_record_user_event_success(self, client, sample_user_event):
        """Test recording user event successfully."""
        user_id = "test_user_5"
        response = client.post(f"/user/{user_id}/events", json=sample_user_event)
        
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Event recorded successfully"
        assert "event_id" in data
    
    def test_record_user_event_missing_type(self, client):
        """Test recording event without event_type."""
        user_id = "test_user_6"
        invalid_event = {
            "event_data": {"category": "electronics"}
        }
        
        response = client.post(f"/user/{user_id}/events", json=invalid_event)
        assert response.status_code == 400
        assert "missing required field" in response.json()["detail"].lower()
    
    def test_record_user_event_invalid_type(self, client):
        """Test recording event with invalid event_type."""
        user_id = "test_user_7"
        invalid_event = {
            "event_type": "invalid_type",
            "event_data": {}
        }
        
        response = client.post(f"/user/{user_id}/events", json=invalid_event)
        assert response.status_code == 400
    
    def test_get_user_events_no_events(self, client):
        """Test getting events for user with no events."""
        user_id = "test_user_8"
        response = client.get(f"/user/{user_id}/events")
        
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == user_id
        assert data["events"] == []
    
    def test_get_user_events_with_events(self, client, sample_user_event):
        """Test getting events for user with events."""
        user_id = "test_user_9"
        
        # Record multiple events
        for i in range(3):
            event_data = sample_user_event.copy()
            event_data["event_data"]["sequence"] = i
            client.post(f"/user/{user_id}/events", json=event_data)
        
        # Get events
        response = client.get(f"/user/{user_id}/events")
        assert response.status_code == 200
        
        data = response.json()
        assert data["user_id"] == user_id
        assert len(data["events"]) == 3
        assert data["total_events"] == 3
        
        # Check events are sorted by timestamp (most recent first)
        timestamps = [event["timestamp"] for event in data["events"]]
        assert timestamps == sorted(timestamps, reverse=True)
    
    def test_get_user_events_with_limit(self, client, sample_user_event):
        """Test getting events with limit parameter."""
        user_id = "test_user_10"
        
        # Record 5 events
        for i in range(5):
            event_data = sample_user_event.copy()
            event_data["event_data"]["sequence"] = i
            client.post(f"/user/{user_id}/events", json=event_data)
        
        # Get events with limit
        response = client.get(f"/user/{user_id}/events?limit=2")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["events"]) == 2
        assert data["total_events"] == 5


class TestUserSegments:
    """Test user segmentation functionality."""
    
    def test_get_segments(self, client):
        """Test getting all segments."""
        response = client.get("/segments")
        assert response.status_code == 200
        
        data = response.json()
        expected_segments = ["high_value", "frequent_buyers", "mobile_users", "young_adults", "tech_enthusiasts"]
        for segment in expected_segments:
            assert segment in data
            assert isinstance(data[segment], list)
    
    def test_get_segment_users_empty(self, client):
        """Test getting users from empty segment."""
        response = client.get("/segments/high_value")
        assert response.status_code == 200
        
        data = response.json()
        assert data["segment_name"] == "high_value"
        assert data["users"] == []
        assert data["count"] == 0
    
    def test_get_segment_users_not_found(self, client):
        """Test getting users from non-existent segment."""
        response = client.get("/segments/nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_add_user_to_segment(self, client):
        """Test adding user to segment."""
        user_id = "test_user_11"
        segment_name = "high_value"
        
        response = client.post(f"/segments/{segment_name}/users/{user_id}")
        assert response.status_code == 200
        
        # Verify user was added
        response = client.get(f"/segments/{segment_name}")
        data = response.json()
        assert user_id in data["users"]
        assert data["count"] == 1
    
    def test_add_user_to_new_segment(self, client):
        """Test adding user to new segment."""
        user_id = "test_user_12"
        segment_name = "new_segment"
        
        response = client.post(f"/segments/{segment_name}/users/{user_id}")
        assert response.status_code == 200
        
        # Verify segment was created and user was added
        response = client.get(f"/segments/{segment_name}")
        assert response.status_code == 200
        data = response.json()
        assert user_id in data["users"]
    
    def test_remove_user_from_segment(self, client):
        """Test removing user from segment."""
        user_id = "test_user_13"
        segment_name = "high_value"
        
        # Add user to segment
        client.post(f"/segments/{segment_name}/users/{user_id}")
        
        # Remove user from segment
        response = client.delete(f"/segments/{segment_name}/users/{user_id}")
        assert response.status_code == 200
        
        # Verify user was removed
        response = client.get(f"/segments/{segment_name}")
        data = response.json()
        assert user_id not in data["users"]
        assert data["count"] == 0


class TestProfileEventIntegration:
    """Test integration between profile updates and event recording."""
    
    def test_event_updates_profile(self, client):
        """Test that recording events updates user profile."""
        user_id = "test_user_14"
        
        # Record a click event
        click_event = {
            "event_type": "click",
            "event_data": {
                "category": "electronics",
                "device_type": "mobile"
            }
        }
        client.post(f"/user/{user_id}/events", json=click_event)
        
        # Check that profile was created and updated
        response = client.get(f"/user/{user_id}/profile")
        assert response.status_code == 200
        
        data = response.json()
        assert "clicker" in data["behaviors"]
        assert "electronics" in data["interests"]
        assert data["demographics"]["device_type"] == "mobile"
    
    def test_purchase_event_adds_to_high_value_segment(self, client):
        """Test that purchase events add users to high_value segment."""
        user_id = "test_user_15"
        
        # Record a purchase event
        purchase_event = {
            "event_type": "purchase",
            "event_data": {
                "product_id": "item_123",
                "amount": 99.99
            }
        }
        client.post(f"/user/{user_id}/events", json=purchase_event)
        
        # Check that user was added to high_value segment
        response = client.get("/segments/high_value")
        data = response.json()
        assert user_id in data["users"]
        
        # Check that user profile includes high_value segment
        response = client.get(f"/user/{user_id}/profile")
        profile_data = response.json()
        assert "high_value" in profile_data["segments"]
    
    def test_multiple_purchases_adds_to_frequent_buyers(self, client):
        """Test that multiple purchases add users to frequent_buyers segment."""
        user_id = "test_user_16"
        
        # Record 3 purchase events
        for i in range(3):
            purchase_event = {
                "event_type": "purchase",
                "event_data": {
                    "product_id": f"item_{i}",
                    "amount": 50.0
                }
            }
            client.post(f"/user/{user_id}/events", json=purchase_event)
        
        # Check that user was added to frequent_buyers segment
        response = client.get("/segments/frequent_buyers")
        data = response.json()
        assert user_id in data["users"]
    
    def test_tech_interests_adds_to_tech_enthusiasts(self, client, sample_user_profile):
        """Test that tech interests add users to tech_enthusiasts segment."""
        user_id = "test_user_17"
        
        # Update profile with tech interests
        tech_profile = sample_user_profile.copy()
        tech_profile["interests"] = ["technology", "gadgets"]
        
        client.put(f"/user/{user_id}/profile", json=tech_profile)
        
        # Check that user was added to tech_enthusiasts segment
        response = client.get("/segments/tech_enthusiasts")
        data = response.json()
        assert user_id in data["users"]


class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_invalid_user_id_format(self, client):
        """Test handling of invalid user ID format."""
        invalid_user_id = "user with spaces"
        profile_data = {"demographics": {"age": 25}}
        
        response = client.put(f"/user/{invalid_user_id}/profile", json=profile_data)
        assert response.status_code == 400
    
    def test_malformed_json_request(self, client):
        """Test handling of malformed JSON in request."""
        user_id = "test_user_18"
        
        # Send malformed JSON
        response = client.put(
            f"/user/{user_id}/profile",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422  # Unprocessable Entity


class TestConcurrency:
    """Test concurrent operations."""
    
    def test_concurrent_profile_updates(self, client, sample_user_profile):
        """Test concurrent profile updates for same user."""
        user_id = "test_user_19"
        
        # Simulate concurrent updates
        update1 = {"interests": ["sports"]}
        update2 = {"interests": ["music"]}
        
        response1 = client.put(f"/user/{user_id}/profile", json=update1)
        response2 = client.put(f"/user/{user_id}/profile", json=update2)
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        # Final profile should contain both interests
        response = client.get(f"/user/{user_id}/profile")
        data = response.json()
        assert "sports" in data["interests"]
        assert "music" in data["interests"]


if __name__ == "__main__":
    pytest.main([__file__])