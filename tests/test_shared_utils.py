"""
Tests for shared utilities.
"""

import pytest
from datetime import datetime
from shared.utils import (
    generate_id, get_current_timestamp, validate_model_data,
    serialize_model, create_error_response, create_health_response,
    validate_bid_request_data, calculate_auction_metrics
)
from shared.models import Campaign, BidRequest, AdSlot, Device, Geo


def test_generate_id():
    """Test ID generation."""
    id1 = generate_id()
    id2 = generate_id()
    
    assert isinstance(id1, str)
    assert isinstance(id2, str)
    assert id1 != id2  # Should be unique
    assert len(id1) > 0


def test_get_current_timestamp():
    """Test timestamp generation."""
    timestamp = get_current_timestamp()
    assert isinstance(timestamp, datetime)


def test_validate_model_data():
    """Test model validation from dictionary."""
    # Valid data
    campaign_data = {
        "id": "camp_123",
        "name": "Test Campaign",
        "advertiser_id": "adv_456",
        "budget": 1000.0
    }
    
    campaign = validate_model_data(Campaign, campaign_data)
    assert isinstance(campaign, Campaign)
    assert campaign.id == "camp_123"
    
    # Invalid data
    invalid_data = {
        "id": "",  # Empty ID should fail validation
        "name": "Test Campaign",
        "advertiser_id": "adv_456",
        "budget": 1000.0
    }
    
    with pytest.raises(Exception):
        validate_model_data(Campaign, invalid_data)


def test_serialize_model():
    """Test model serialization."""
    campaign = Campaign(
        id="camp_123",
        name="Test Campaign",
        advertiser_id="adv_456",
        budget=1000.0
    )
    
    serialized = serialize_model(campaign)
    assert isinstance(serialized, dict)
    assert serialized['id'] == "camp_123"
    assert serialized['budget'] == 1000.0
    
    # Test exclude_none
    serialized_no_none = serialize_model(campaign, exclude_none=True)
    assert isinstance(serialized_no_none, dict)


def test_create_error_response():
    """Test error response creation."""
    error_response = create_error_response(
        "INVALID_REQUEST",
        "Missing required field",
        {"field": "user_id"}
    )
    
    assert error_response['error_code'] == "INVALID_REQUEST"
    assert error_response['message'] == "Missing required field"
    assert error_response['details']['field'] == "user_id"
    assert 'timestamp' in error_response


def test_create_health_response():
    """Test health response creation."""
    health_response = create_health_response("healthy", {"uptime": "5m"})
    
    assert health_response['status'] == "healthy"
    assert health_response['details']['uptime'] == "5m"
    assert 'timestamp' in health_response


def test_validate_bid_request_data():
    """Test bid request data validation."""
    # Valid bid request data
    valid_data = {
        "id": "req_001",
        "user_id": "user_123",
        "ad_slot": {
            "id": "slot_001",
            "width": 300,
            "height": 250,
            "position": "above_fold"
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
        }
    }
    
    assert validate_bid_request_data(valid_data) is True
    
    # Invalid data - missing required field
    invalid_data = valid_data.copy()
    del invalid_data['user_id']
    
    assert validate_bid_request_data(invalid_data) is False
    
    # Invalid data - missing nested field
    invalid_nested = valid_data.copy()
    del invalid_nested['ad_slot']['width']
    
    assert validate_bid_request_data(invalid_nested) is False


def test_calculate_auction_metrics():
    """Test auction metrics calculation."""
    # Test with multiple bids
    bids = [
        {"price": 1.50, "dsp_id": "dsp1"},
        {"price": 2.00, "dsp_id": "dsp2"},
        {"price": 1.25, "dsp_id": "dsp3"}
    ]
    
    metrics = calculate_auction_metrics(bids)
    
    assert metrics['total_bids'] == 3
    assert metrics['highest_bid'] == 2.00
    assert metrics['lowest_bid'] == 1.25
    assert abs(metrics['average_bid'] - 1.583333333333333) < 0.0001  # (1.5 + 2.0 + 1.25) / 3
    assert metrics['bid_range'] == 0.75  # 2.0 - 1.25
    
    # Test with empty bids
    empty_metrics = calculate_auction_metrics([])
    
    assert empty_metrics['total_bids'] == 0
    assert empty_metrics['highest_bid'] == 0.0
    assert empty_metrics['average_bid'] == 0.0
    assert empty_metrics['bid_range'] == 0.0
    
    # Test with single bid
    single_bid = [{"price": 1.75, "dsp_id": "dsp1"}]
    single_metrics = calculate_auction_metrics(single_bid)
    
    assert single_metrics['total_bids'] == 1
    assert single_metrics['highest_bid'] == 1.75
    assert single_metrics['lowest_bid'] == 1.75
    assert single_metrics['average_bid'] == 1.75
    assert single_metrics['bid_range'] == 0.0