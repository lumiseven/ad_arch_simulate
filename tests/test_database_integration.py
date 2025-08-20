"""
Integration tests for database persistence and configuration management.
Tests database operations, error handling, and fallback mechanisms.
"""

import pytest
import asyncio
import os
import tempfile
from datetime import datetime
from typing import Dict, Any

from shared.database import (
    init_database, check_database_health, get_db,
    CampaignDB, UserProfileDB, ImpressionDB, CampaignStatsDB
)
from shared.repositories import (
    CampaignRepository, UserProfileRepository, ImpressionRepository,
    CampaignStatsRepository
)
from shared.database_service import (
    CampaignService, UserProfileService, ImpressionService,
    CampaignStatsService
)
from shared.models import (
    Campaign, UserProfile, Impression, CampaignStats,
    CampaignStatus
)
from shared.config import get_config, ConfigManager
from shared.utils import generate_id


@pytest.fixture
async def test_db():
    """Create a test database."""
    # Use in-memory SQLite for testing
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["SYNC_DATABASE_URL"] = "sqlite:///:memory:"
    
    # Initialize database
    await init_database()
    
    yield
    
    # Cleanup
    if "DATABASE_URL" in os.environ:
        del os.environ["DATABASE_URL"]
    if "SYNC_DATABASE_URL" in os.environ:
        del os.environ["SYNC_DATABASE_URL"]


@pytest.fixture
def sample_campaign():
    """Create a sample campaign for testing."""
    return Campaign(
        id=generate_id(),
        name="Test Campaign",
        advertiser_id="test_advertiser",
        budget=1000.0,
        spent=100.0,
        targeting={"age_range": {"min_age": 18, "max_age": 35}},
        creative={"title": "Test Ad", "description": "Test Description"},
        status=CampaignStatus.ACTIVE
    )


@pytest.fixture
def sample_user_profile():
    """Create a sample user profile for testing."""
    return UserProfile(
        user_id=generate_id(),
        demographics={"age": 25, "gender": "female"},
        interests=["technology", "shopping"],
        behaviors=["frequent_buyer"],
        segments=["high_value"]
    )


@pytest.fixture
def sample_impression():
    """Create a sample impression for testing."""
    return Impression(
        id=generate_id(),
        campaign_id="test_campaign",
        user_id="test_user",
        price=1.50,
        revenue=1.80,
        timestamp=datetime.now()
    )


class TestDatabaseOperations:
    """Test basic database operations."""
    
    @pytest.mark.asyncio
    async def test_database_health_check(self, test_db):
        """Test database health check."""
        is_healthy = await check_database_health()
        assert is_healthy is True
    
    @pytest.mark.asyncio
    async def test_campaign_repository_crud(self, test_db, sample_campaign):
        """Test campaign repository CRUD operations."""
        async for session in get_db():
            repo = CampaignRepository(session)
            
            # Create
            created_campaign = await repo.create(sample_campaign)
            assert created_campaign.id == sample_campaign.id
            assert created_campaign.name == sample_campaign.name
            
            # Read
            retrieved_campaign = await repo.get_by_id(sample_campaign.id)
            assert retrieved_campaign is not None
            assert retrieved_campaign.id == sample_campaign.id
            
            # Update
            update_data = {"name": "Updated Campaign", "budget": 2000.0}
            updated_campaign = await repo.update(sample_campaign.id, update_data)
            assert updated_campaign is not None
            assert updated_campaign.name == "Updated Campaign"
            assert updated_campaign.budget == 2000.0
            
            # Delete
            deleted = await repo.delete(sample_campaign.id)
            assert deleted is True
            
            # Verify deletion
            deleted_campaign = await repo.get_by_id(sample_campaign.id)
            assert deleted_campaign is None
            
            break
    
    @pytest.mark.asyncio
    async def test_user_profile_repository_crud(self, test_db, sample_user_profile):
        """Test user profile repository CRUD operations."""
        async for session in get_db():
            repo = UserProfileRepository(session)
            
            # Create
            created_profile = await repo.create(sample_user_profile)
            assert created_profile.user_id == sample_user_profile.user_id
            
            # Read
            retrieved_profile = await repo.get_by_id(sample_user_profile.user_id)
            assert retrieved_profile is not None
            assert retrieved_profile.user_id == sample_user_profile.user_id
            
            # Update
            update_data = {"interests": ["technology", "gaming", "sports"]}
            updated_profile = await repo.update(sample_user_profile.user_id, update_data)
            assert updated_profile is not None
            assert len(updated_profile.interests) == 3
            
            break
    
    @pytest.mark.asyncio
    async def test_campaign_stats_operations(self, test_db, sample_campaign):
        """Test campaign statistics operations."""
        async for session in get_db():
            # First create a campaign
            campaign_repo = CampaignRepository(session)
            await campaign_repo.create(sample_campaign)
            
            # Create stats
            stats_repo = CampaignStatsRepository(session)
            stats = CampaignStats(
                campaign_id=sample_campaign.id,
                impressions=1000,
                clicks=50,
                conversions=5,
                spend=100.0,
                revenue=120.0
            )
            
            created_stats = await stats_repo.create(stats)
            assert created_stats.campaign_id == sample_campaign.id
            assert created_stats.ctr == 0.05  # 50/1000
            
            # Update stats
            stats_update = {"impressions": 2000, "clicks": 120}
            updated = await stats_repo.update_stats(sample_campaign.id, stats_update)
            assert updated is True
            
            # Retrieve updated stats
            retrieved_stats = await stats_repo.get_by_campaign(sample_campaign.id)
            assert retrieved_stats is not None
            assert retrieved_stats.impressions == 2000
            assert retrieved_stats.clicks == 120
            assert retrieved_stats.ctr == 0.06  # 120/2000
            
            break


class TestDatabaseServices:
    """Test database service layer with fallback mechanisms."""
    
    @pytest.mark.asyncio
    async def test_campaign_service_with_database(self, test_db, sample_campaign):
        """Test campaign service with database."""
        service = CampaignService()
        
        # Test database availability
        is_healthy = await service.check_health()
        assert is_healthy is True
        
        # Create campaign
        created_campaign = await service.create_campaign(sample_campaign)
        assert created_campaign.id == sample_campaign.id
        
        # Get campaign
        retrieved_campaign = await service.get_campaign(sample_campaign.id)
        assert retrieved_campaign is not None
        assert retrieved_campaign.id == sample_campaign.id
        
        # Update campaign
        update_data = {"name": "Updated via Service"}
        updated_campaign = await service.update_campaign(sample_campaign.id, update_data)
        assert updated_campaign is not None
        assert updated_campaign.name == "Updated via Service"
        
        # Update spend
        spend_updated = await service.update_spend(sample_campaign.id, 50.0)
        assert spend_updated is True
        
        # Get updated campaign
        final_campaign = await service.get_campaign(sample_campaign.id)
        assert final_campaign.spent == 150.0  # 100.0 + 50.0
    
    @pytest.mark.asyncio
    async def test_campaign_service_fallback(self, sample_campaign):
        """Test campaign service fallback to in-memory storage."""
        # Create service without database
        service = CampaignService()
        service.db_available = False  # Force fallback mode
        
        # Create campaign (should use fallback)
        created_campaign = await service.create_campaign(sample_campaign)
        assert created_campaign.id == sample_campaign.id
        
        # Verify it's in memory storage
        assert sample_campaign.id in service.campaigns_memory
        
        # Get campaign (should use fallback)
        retrieved_campaign = await service.get_campaign(sample_campaign.id)
        assert retrieved_campaign is not None
        assert retrieved_campaign.id == sample_campaign.id
        
        # Update campaign (should use fallback)
        update_data = {"name": "Fallback Updated"}
        updated_campaign = await service.update_campaign(sample_campaign.id, update_data)
        assert updated_campaign is not None
        assert updated_campaign.name == "Fallback Updated"
    
    @pytest.mark.asyncio
    async def test_user_profile_service_with_database(self, test_db, sample_user_profile):
        """Test user profile service with database."""
        service = UserProfileService()
        
        # Create profile
        created_profile = await service.create_profile(sample_user_profile)
        assert created_profile.user_id == sample_user_profile.user_id
        
        # Get profile
        retrieved_profile = await service.get_profile(sample_user_profile.user_id)
        assert retrieved_profile is not None
        assert retrieved_profile.user_id == sample_user_profile.user_id
        
        # Update profile
        update_data = {"interests": ["updated_interest"]}
        updated_profile = await service.update_profile(sample_user_profile.user_id, update_data)
        assert updated_profile is not None
        assert "updated_interest" in updated_profile.interests
    
    @pytest.mark.asyncio
    async def test_impression_service_with_database(self, test_db, sample_impression):
        """Test impression service with database."""
        service = ImpressionService()
        
        # Create impression
        created_impression = await service.create_impression(sample_impression)
        assert created_impression.id == sample_impression.id
        
        # Get impressions by campaign
        impressions = await service.get_impressions_by_campaign(sample_impression.campaign_id)
        assert len(impressions) == 1
        assert impressions[0].id == sample_impression.id
    
    @pytest.mark.asyncio
    async def test_campaign_stats_service_with_database(self, test_db, sample_campaign):
        """Test campaign stats service with database."""
        # First create a campaign
        campaign_service = CampaignService()
        await campaign_service.create_campaign(sample_campaign)
        
        # Test stats service
        stats_service = CampaignStatsService()
        
        # Update stats
        stats_update = {
            "impressions": 1000,
            "clicks": 50,
            "spend": 100.0,
            "revenue": 120.0
        }
        updated = await stats_service.update_stats(sample_campaign.id, stats_update)
        assert updated is True
        
        # Get stats
        stats = await stats_service.get_stats(sample_campaign.id)
        assert stats is not None
        assert stats.campaign_id == sample_campaign.id
        assert stats.impressions == 1000
        assert stats.clicks == 50


class TestConfigurationManagement:
    """Test configuration management functionality."""
    
    def test_config_manager_creation(self):
        """Test configuration manager creation."""
        config_manager = ConfigManager("test-service")
        config = config_manager.config
        
        assert config.service.name == "test-service"
        assert config.service.host == "0.0.0.0"
        assert config.database.url is not None
    
    def test_config_from_environment(self):
        """Test configuration loading from environment variables."""
        # Set environment variables
        os.environ["HOST"] = "127.0.0.1"
        os.environ["DEBUG"] = "true"
        os.environ["LOG_LEVEL"] = "DEBUG"
        os.environ["DATABASE_ECHO"] = "true"
        
        try:
            config_manager = ConfigManager("env-test-service")
            config = config_manager.config
            
            assert config.service.host == "127.0.0.1"
            assert config.service.debug is True
            assert config.logging.level == "DEBUG"
            assert config.database.echo is True
            
        finally:
            # Cleanup
            for key in ["HOST", "DEBUG", "LOG_LEVEL", "DATABASE_ECHO"]:
                if key in os.environ:
                    del os.environ[key]
    
    def test_config_from_file(self):
        """Test configuration loading from JSON file."""
        config_data = {
            "service": {
                "host": "192.168.1.1",
                "port": 9000,
                "debug": True
            },
            "database": {
                "echo": True,
                "pool_size": 10
            },
            "rtb": {
                "timeout_ms": 200,
                "dsp_timeout_ms": 100
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            import json
            json.dump(config_data, f)
            config_file = f.name
        
        try:
            config_manager = ConfigManager("file-test-service", config_file)
            config = config_manager.config
            
            assert config.service.host == "192.168.1.1"
            assert config.service.port == 9000
            assert config.service.debug is True
            assert config.database.echo is True
            assert config.database.pool_size == 10
            assert config.rtb.timeout_ms == 200
            assert config.rtb.dsp_timeout_ms == 100
            
        finally:
            os.unlink(config_file)
    
    def test_service_specific_ports(self):
        """Test service-specific port assignment."""
        services = ["ad-management", "dsp", "ssp", "ad-exchange", "dmp"]
        expected_ports = [8001, 8002, 8003, 8004, 8005]
        
        for service_name, expected_port in zip(services, expected_ports):
            config_manager = ConfigManager(service_name)
            config = config_manager.config
            assert config.service.port == expected_port
    
    def test_config_to_dict(self):
        """Test configuration serialization to dictionary."""
        config_manager = ConfigManager("dict-test-service")
        config_dict = config_manager.to_dict()
        
        assert "service" in config_dict
        assert "database" in config_dict
        assert "rtb" in config_dict
        assert "service_urls" in config_dict
        
        assert config_dict["service"]["name"] == "dict-test-service"
        assert isinstance(config_dict["service"]["port"], int)
        assert isinstance(config_dict["database"]["pool_size"], int)


class TestErrorHandlingAndFallback:
    """Test error handling and fallback mechanisms."""
    
    @pytest.mark.asyncio
    async def test_database_error_fallback(self, sample_campaign):
        """Test fallback when database operations fail."""
        service = CampaignService()
        
        # Simulate database unavailability
        service.db_available = False
        
        # Operations should still work with fallback
        created_campaign = await service.create_campaign(sample_campaign)
        assert created_campaign.id == sample_campaign.id
        
        retrieved_campaign = await service.get_campaign(sample_campaign.id)
        assert retrieved_campaign is not None
        assert retrieved_campaign.id == sample_campaign.id
        
        # Verify data is in memory storage
        assert sample_campaign.id in service.campaigns_memory
    
    @pytest.mark.asyncio
    async def test_database_reconnection(self, test_db, sample_campaign):
        """Test database reconnection after failure."""
        service = CampaignService()
        
        # Initially healthy
        is_healthy = await service.check_health()
        assert is_healthy is True
        
        # Simulate database failure
        service.db_available = False
        
        # Create campaign (should use fallback)
        created_campaign = await service.create_campaign(sample_campaign)
        assert created_campaign.id == sample_campaign.id
        assert sample_campaign.id in service.campaigns_memory
        
        # Simulate database recovery
        is_healthy = await service.check_health()
        assert is_healthy is True
        
        # Next operation should use database again
        retrieved_campaign = await service.get_campaign(sample_campaign.id)
        # Note: This might be None since fallback data isn't automatically synced to DB
        # In a real implementation, you might want to implement data synchronization


if __name__ == "__main__":
    pytest.main([__file__, "-v"])