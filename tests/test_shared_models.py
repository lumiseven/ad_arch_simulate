"""
Tests for shared data models.
"""

import pytest
from datetime import datetime
from pydantic import ValidationError
from shared.models import (
    Campaign, CampaignStatus, UserProfile, BidRequest, BidResponse,
    Impression, ErrorResponse, HealthCheck, AdSlot, Device, Geo,
    AuctionResult, UserEvent, CampaignStats
)


def test_campaign_model():
    """Test Campaign model creation and validation."""
    campaign = Campaign(
        id="camp_123",
        name="Test Campaign",
        advertiser_id="adv_456",
        budget=1000.0,
        targeting={"age": "18-35", "interests": ["tech"]},
        creative={"title": "Test Ad", "image_url": "http://example.com/ad.jpg"}
    )
    
    assert campaign.id == "camp_123"
    assert campaign.name == "Test Campaign"
    assert campaign.budget == 1000.0
    assert campaign.spent == 0.0  # default value
    assert campaign.status == CampaignStatus.DRAFT  # default value
    assert isinstance(campaign.created_at, datetime)


def test_user_profile_model():
    """Test UserProfile model creation and validation."""
    profile = UserProfile(
        user_id="user_789",
        demographics={"age": 25, "gender": "M"},
        interests=["tech", "sports"],
        behaviors=["frequent_shopper"],
        segments=["tech_enthusiasts"]
    )
    
    assert profile.user_id == "user_789"
    assert "tech" in profile.interests
    assert "frequent_shopper" in profile.behaviors
    assert isinstance(profile.last_updated, datetime)


def test_bid_request_model():
    """Test BidRequest model creation and validation."""
    ad_slot = AdSlot(
        id="slot_001",
        width=300,
        height=250,
        position="above_fold",
        floor_price=0.5
    )
    
    device = Device(
        type="mobile",
        os="iOS",
        browser="Safari",
        ip="192.168.1.1"
    )
    
    geo = Geo(
        country="US",
        region="CA",
        city="San Francisco"
    )
    
    bid_request = BidRequest(
        id="req_001",
        user_id="user_789",
        ad_slot=ad_slot,
        device=device,
        geo=geo
    )
    
    assert bid_request.id == "req_001"
    assert bid_request.ad_slot.width == 300
    assert bid_request.device.type == "mobile"
    assert bid_request.geo.country == "US"


def test_bid_response_model():
    """Test BidResponse model creation and validation."""
    bid_response = BidResponse(
        request_id="req_001",
        price=1.25,
        creative={"title": "Great Product", "image_url": "http://example.com/ad.jpg"},
        campaign_id="camp_123",
        dsp_id="dsp_001"
    )
    
    assert bid_response.request_id == "req_001"
    assert bid_response.price == 1.25
    assert bid_response.campaign_id == "camp_123"


def test_health_check_model():
    """Test HealthCheck model creation."""
    health = HealthCheck(status="healthy")
    
    assert health.status == "healthy"
    assert health.version == "0.1.0"  # default value
    assert isinstance(health.timestamp, datetime)


def test_error_response_model():
    """Test ErrorResponse model creation."""
    error = ErrorResponse(
        error_code="INVALID_REQUEST",
        message="Missing required field",
        details={"field": "user_id"}
    )
    
    assert error.error_code == "INVALID_REQUEST"
    assert error.message == "Missing required field"
    assert error.details["field"] == "user_id"
    assert isinstance(error.timestamp, datetime)


# Validation Tests
def test_campaign_validation():
    """Test Campaign model validation."""
    # Test valid campaign
    campaign = Campaign(
        id="camp_123",
        name="Test Campaign",
        advertiser_id="adv_456",
        budget=1000.0
    )
    assert campaign.spent <= campaign.budget
    
    # Test invalid ID format
    with pytest.raises(ValidationError):
        Campaign(
            id="camp@123",  # Invalid character
            name="Test Campaign",
            advertiser_id="adv_456",
            budget=1000.0
        )
    
    # Test empty name
    with pytest.raises(ValidationError):
        Campaign(
            id="camp_123",
            name="",  # Empty name
            advertiser_id="adv_456",
            budget=1000.0
        )
    
    # Test negative budget
    with pytest.raises(ValidationError):
        Campaign(
            id="camp_123",
            name="Test Campaign",
            advertiser_id="adv_456",
            budget=-100.0  # Negative budget
        )


def test_user_profile_validation():
    """Test UserProfile model validation."""
    # Test valid profile
    profile = UserProfile(
        user_id="user_123",
        interests=["tech", "sports"],
        behaviors=["frequent_shopper"]
    )
    assert len(profile.interests) == 2
    
    # Test invalid user ID
    with pytest.raises(ValidationError):
        UserProfile(user_id="user@123")  # Invalid character
    
    # Test empty tags
    with pytest.raises(ValidationError):
        UserProfile(
            user_id="user_123",
            interests=["tech", ""]  # Empty tag
        )


def test_device_validation():
    """Test Device model validation."""
    # Test valid device
    device = Device(
        type="mobile",
        os="iOS",
        browser="Safari",
        ip="192.168.1.1"
    )
    assert device.type == "mobile"
    
    # Test invalid device type
    with pytest.raises(ValidationError):
        Device(
            type="smartwatch",  # Invalid type
            os="iOS",
            browser="Safari",
            ip="192.168.1.1"
        )
    
    # Test invalid IP
    with pytest.raises(ValidationError):
        Device(
            type="mobile",
            os="iOS",
            browser="Safari",
            ip="invalid.ip"  # Invalid IP format
        )


def test_bid_response_validation():
    """Test BidResponse model validation."""
    # Test valid bid response
    bid_response = BidResponse(
        request_id="req_001",
        price=1.25,
        creative={"title": "Great Product", "image_url": "http://example.com/ad.jpg"},
        campaign_id="camp_123",
        dsp_id="dsp_001"
    )
    assert bid_response.price == 1.25
    
    # Test missing creative title
    with pytest.raises(ValidationError):
        BidResponse(
            request_id="req_001",
            price=1.25,
            creative={"image_url": "http://example.com/ad.jpg"},  # Missing title
            campaign_id="camp_123",
            dsp_id="dsp_001"
        )
    
    # Test invalid price precision
    with pytest.raises(ValidationError):
        BidResponse(
            request_id="req_001",
            price=1.123456789,  # Too many decimal places
            creative={"title": "Great Product"},
            campaign_id="camp_123",
            dsp_id="dsp_001"
        )


def test_health_check_validation():
    """Test HealthCheck model validation."""
    # Test valid health check
    health = HealthCheck(status="healthy")
    assert health.status == "healthy"
    
    # Test invalid status
    with pytest.raises(ValidationError):
        HealthCheck(status="unknown")  # Invalid status


def test_auction_result_model():
    """Test AuctionResult model."""
    bid_response = BidResponse(
        request_id="req_001",
        price=1.25,
        creative={"title": "Great Product"},
        campaign_id="camp_123",
        dsp_id="dsp_001"
    )
    
    auction = AuctionResult(
        auction_id="auction_001",
        request_id="req_001",
        winning_bid=bid_response,
        all_bids=[bid_response],
        auction_price=1.25
    )
    
    assert auction.auction_id == "auction_001"
    assert auction.winning_bid.price == 1.25
    assert len(auction.all_bids) == 1


def test_user_event_model():
    """Test UserEvent model."""
    event = UserEvent(
        event_id="event_001",
        user_id="user_123",
        event_type="click",
        event_data={"page": "homepage"}
    )
    
    assert event.event_type == "click"
    assert event.event_data["page"] == "homepage"
    
    # Test invalid event type
    with pytest.raises(ValidationError):
        UserEvent(
            event_id="event_001",
            user_id="user_123",
            event_type="invalid_event"  # Invalid event type
        )


def test_campaign_stats_model():
    """Test CampaignStats model with derived metrics."""
    stats = CampaignStats(
        campaign_id="camp_123",
        impressions=1000,
        clicks=50,
        spend=25.0
    )
    
    # Check calculated metrics
    assert stats.ctr == 0.05  # 50/1000
    assert stats.cpc == 0.5   # 25.0/50
    
    # Test with zero impressions
    stats_zero = CampaignStats(
        campaign_id="camp_123",
        impressions=0,
        clicks=0,
        spend=0.0
    )
    
    assert stats_zero.ctr == 0.0
    assert stats_zero.cpc == 0.0


def test_impression_model():
    """Test Impression model creation and validation."""
    impression = Impression(
        id="imp_001",
        campaign_id="camp_123",
        user_id="user_789",
        price=1.25,
        revenue=1.0
    )
    
    assert impression.id == "imp_001"
    assert impression.price == 1.25
    assert impression.revenue == 1.0
    assert isinstance(impression.timestamp, datetime)


def test_campaign_spent_validation():
    """Test Campaign spent validation against budget."""
    # Test valid case where spent is within budget
    campaign = Campaign(
        id="camp_123",
        name="Test Campaign",
        advertiser_id="adv_456",
        budget=1000.0,
        spent=500.0
    )
    assert campaign.spent == 500.0
    
    # Test invalid case where spent exceeds budget
    with pytest.raises(ValidationError):
        Campaign(
            id="camp_123",
            name="Test Campaign",
            advertiser_id="adv_456",
            budget=1000.0,
            spent=1500.0  # Exceeds budget
        )


def test_ad_slot_validation():
    """Test AdSlot model validation."""
    # Test valid ad slot
    ad_slot = AdSlot(
        id="slot_001",
        width=300,
        height=250,
        position="above_fold",
        floor_price=0.5
    )
    assert ad_slot.width == 300
    assert ad_slot.height == 250
    
    # Test invalid dimensions
    with pytest.raises(ValidationError):
        AdSlot(
            id="slot_001",
            width=0,  # Invalid width
            height=250,
            position="above_fold"
        )
    
    with pytest.raises(ValidationError):
        AdSlot(
            id="slot_001",
            width=300,
            height=-100,  # Invalid height
            position="above_fold"
        )


def test_geo_model():
    """Test Geo model creation."""
    geo = Geo(
        country="US",
        region="CA",
        city="San Francisco",
        lat=37.7749,
        lon=-122.4194
    )
    
    assert geo.country == "US"
    assert geo.lat == 37.7749
    assert geo.lon == -122.4194


def test_campaign_status_enum():
    """Test CampaignStatus enum values."""
    campaign = Campaign(
        id="camp_123",
        name="Test Campaign",
        advertiser_id="adv_456",
        budget=1000.0,
        status=CampaignStatus.ACTIVE
    )
    
    assert campaign.status == CampaignStatus.ACTIVE
    assert campaign.status.value == "active"


def test_model_serialization():
    """Test model JSON serialization."""
    campaign = Campaign(
        id="camp_123",
        name="Test Campaign",
        advertiser_id="adv_456",
        budget=1000.0
    )
    
    # Test JSON serialization
    json_data = campaign.model_dump()
    assert json_data['id'] == "camp_123"
    assert json_data['budget'] == 1000.0
    
    # Test JSON deserialization
    new_campaign = Campaign.model_validate(json_data)
    assert new_campaign.id == campaign.id
    assert new_campaign.budget == campaign.budget


def test_empty_creative_validation():
    """Test BidResponse with empty creative title."""
    with pytest.raises(ValidationError):
        BidResponse(
            request_id="req_001",
            price=1.25,
            creative={"title": ""},  # Empty title
            campaign_id="camp_123",
            dsp_id="dsp_001"
        )


def test_zero_price_validation():
    """Test BidResponse with zero or negative price."""
    with pytest.raises(ValidationError):
        BidResponse(
            request_id="req_001",
            price=0.0,  # Zero price not allowed
            creative={"title": "Great Product"},
            campaign_id="camp_123",
            dsp_id="dsp_001"
        )
    
    with pytest.raises(ValidationError):
        BidResponse(
            request_id="req_001",
            price=-1.0,  # Negative price not allowed
            creative={"title": "Great Product"},
            campaign_id="camp_123",
            dsp_id="dsp_001"
        )


def test_campaign_stats_edge_cases():
    """Test CampaignStats with edge cases."""
    # Test with all zero values
    stats = CampaignStats(
        campaign_id="camp_123",
        impressions=0,
        clicks=0,
        spend=0.0
    )
    
    assert stats.ctr == 0.0
    assert stats.cpc == 0.0
    
    # Test with clicks but no impressions (edge case)
    stats_edge = CampaignStats(
        campaign_id="camp_123",
        impressions=0,
        clicks=5,  # Clicks without impressions (unusual but possible)
        spend=10.0
    )
    
    assert stats_edge.ctr == 0.0  # No impressions means CTR is 0
    assert stats_edge.cpc == 2.0  # 10.0 / 5


def test_user_profile_empty_lists():
    """Test UserProfile with empty lists."""
    profile = UserProfile(
        user_id="user_123",
        demographics={"age": 25},
        interests=[],  # Empty list should be allowed
        behaviors=[],
        segments=[]
    )
    
    assert len(profile.interests) == 0
    assert len(profile.behaviors) == 0
    assert len(profile.segments) == 0