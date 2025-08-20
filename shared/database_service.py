"""
Database service integration utilities.
Provides database-aware service functionality with error handling and fallback.
"""

import logging
from typing import Dict, Any, Optional, List, Type, TypeVar
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import get_db, check_database_health, DatabaseError
from shared.repositories import (
    CampaignRepository, UserProfileRepository, ImpressionRepository,
    UserEventRepository, CampaignStatsRepository, AuctionResultRepository
)
from shared.models import (
    Campaign, UserProfile, Impression, UserEvent,
    CampaignStats, AuctionResult
)
from shared.utils import ServiceError

logger = logging.getLogger(__name__)

T = TypeVar('T')


class DatabaseService:
    """Database service wrapper with error handling and fallback mechanisms."""
    
    def __init__(self, fallback_storage: Optional[Dict[str, Any]] = None):
        self.fallback_storage = fallback_storage or {}
        self.db_available = True
        self.logger = logging.getLogger(f"{__name__}.DatabaseService")
    
    async def check_health(self) -> bool:
        """Check database health and update availability status."""
        try:
            self.db_available = await check_database_health()
            return self.db_available
        except Exception as e:
            self.logger.error(f"Database health check failed: {e}")
            self.db_available = False
            return False
    
    @asynccontextmanager
    async def get_session(self):
        """Get database session with error handling."""
        if not self.db_available:
            # Try to reconnect
            await self.check_health()
        
        if self.db_available:
            try:
                async for session in get_db():
                    yield session
                    return
            except Exception as e:
                self.logger.error(f"Database session error: {e}")
                self.db_available = False
        
        # Fallback to None (will trigger in-memory storage)
        yield None
    
    async def with_fallback(self, db_operation, fallback_operation, *args, **kwargs):
        """Execute database operation with fallback to in-memory storage."""
        async with self.get_session() as session:
            if session is not None:
                try:
                    return await db_operation(session, *args, **kwargs)
                except DatabaseError as e:
                    self.logger.warning(f"Database operation failed, using fallback: {e}")
                    self.db_available = False
                except Exception as e:
                    self.logger.error(f"Unexpected database error, using fallback: {e}")
                    self.db_available = False
            
            # Use fallback storage
            self.logger.info("Using fallback in-memory storage")
            return await fallback_operation(*args, **kwargs)


class CampaignService(DatabaseService):
    """Campaign service with database persistence and fallback."""
    
    def __init__(self, fallback_storage: Optional[Dict[str, Campaign]] = None):
        super().__init__()
        self.campaigns_memory = fallback_storage or {}
    
    async def create_campaign(self, campaign: Campaign) -> Campaign:
        """Create a new campaign."""
        async def db_operation(session: AsyncSession, campaign: Campaign) -> Campaign:
            repo = CampaignRepository(session)
            return await repo.create(campaign)
        
        async def fallback_operation(campaign: Campaign) -> Campaign:
            self.campaigns_memory[campaign.id] = campaign
            return campaign
        
        return await self.with_fallback(db_operation, fallback_operation, campaign)
    
    async def get_campaign(self, campaign_id: str) -> Optional[Campaign]:
        """Get campaign by ID."""
        async def db_operation(session: AsyncSession, campaign_id: str) -> Optional[Campaign]:
            repo = CampaignRepository(session)
            return await repo.get_by_id(campaign_id)
        
        async def fallback_operation(campaign_id: str) -> Optional[Campaign]:
            return self.campaigns_memory.get(campaign_id)
        
        return await self.with_fallback(db_operation, fallback_operation, campaign_id)
    
    async def update_campaign(self, campaign_id: str, update_data: Dict[str, Any]) -> Optional[Campaign]:
        """Update campaign."""
        async def db_operation(session: AsyncSession, campaign_id: str, update_data: Dict[str, Any]) -> Optional[Campaign]:
            repo = CampaignRepository(session)
            return await repo.update(campaign_id, update_data)
        
        async def fallback_operation(campaign_id: str, update_data: Dict[str, Any]) -> Optional[Campaign]:
            if campaign_id in self.campaigns_memory:
                campaign = self.campaigns_memory[campaign_id]
                # Update campaign fields
                for key, value in update_data.items():
                    if hasattr(campaign, key):
                        setattr(campaign, key, value)
                return campaign
            return None
        
        return await self.with_fallback(db_operation, fallback_operation, campaign_id, update_data)
    
    async def delete_campaign(self, campaign_id: str) -> bool:
        """Delete campaign."""
        async def db_operation(session: AsyncSession, campaign_id: str) -> bool:
            repo = CampaignRepository(session)
            return await repo.delete(campaign_id)
        
        async def fallback_operation(campaign_id: str) -> bool:
            if campaign_id in self.campaigns_memory:
                del self.campaigns_memory[campaign_id]
                return True
            return False
        
        return await self.with_fallback(db_operation, fallback_operation, campaign_id)
    
    async def list_campaigns(self, limit: int = 100, offset: int = 0) -> List[Campaign]:
        """List campaigns with pagination."""
        async def db_operation(session: AsyncSession, limit: int, offset: int) -> List[Campaign]:
            repo = CampaignRepository(session)
            return await repo.list_all(limit, offset)
        
        async def fallback_operation(limit: int, offset: int) -> List[Campaign]:
            campaigns = list(self.campaigns_memory.values())
            return campaigns[offset:offset + limit]
        
        return await self.with_fallback(db_operation, fallback_operation, limit, offset)
    
    async def get_active_campaigns(self) -> List[Campaign]:
        """Get active campaigns."""
        async def db_operation(session: AsyncSession) -> List[Campaign]:
            repo = CampaignRepository(session)
            return await repo.get_active_campaigns()
        
        async def fallback_operation() -> List[Campaign]:
            return [c for c in self.campaigns_memory.values() if c.status == "active"]
        
        return await self.with_fallback(db_operation, fallback_operation)
    
    async def update_spend(self, campaign_id: str, amount: float) -> bool:
        """Update campaign spend."""
        async def db_operation(session: AsyncSession, campaign_id: str, amount: float) -> bool:
            repo = CampaignRepository(session)
            return await repo.update_spend(campaign_id, amount)
        
        async def fallback_operation(campaign_id: str, amount: float) -> bool:
            if campaign_id in self.campaigns_memory:
                campaign = self.campaigns_memory[campaign_id]
                new_spent = campaign.spent + amount
                if new_spent <= campaign.budget:
                    campaign.spent = new_spent
                    return True
            return False
        
        return await self.with_fallback(db_operation, fallback_operation, campaign_id, amount)


class UserProfileService(DatabaseService):
    """User profile service with database persistence and fallback."""
    
    def __init__(self, fallback_storage: Optional[Dict[str, UserProfile]] = None):
        super().__init__()
        self.profiles_memory = fallback_storage or {}
    
    async def create_profile(self, profile: UserProfile) -> UserProfile:
        """Create user profile."""
        async def db_operation(session: AsyncSession, profile: UserProfile) -> UserProfile:
            repo = UserProfileRepository(session)
            return await repo.create(profile)
        
        async def fallback_operation(profile: UserProfile) -> UserProfile:
            self.profiles_memory[profile.user_id] = profile
            return profile
        
        return await self.with_fallback(db_operation, fallback_operation, profile)
    
    async def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get user profile."""
        async def db_operation(session: AsyncSession, user_id: str) -> Optional[UserProfile]:
            repo = UserProfileRepository(session)
            return await repo.get_by_id(user_id)
        
        async def fallback_operation(user_id: str) -> Optional[UserProfile]:
            return self.profiles_memory.get(user_id)
        
        return await self.with_fallback(db_operation, fallback_operation, user_id)
    
    async def update_profile(self, user_id: str, update_data: Dict[str, Any]) -> Optional[UserProfile]:
        """Update user profile."""
        async def db_operation(session: AsyncSession, user_id: str, update_data: Dict[str, Any]) -> Optional[UserProfile]:
            repo = UserProfileRepository(session)
            return await repo.update(user_id, update_data)
        
        async def fallback_operation(user_id: str, update_data: Dict[str, Any]) -> Optional[UserProfile]:
            if user_id in self.profiles_memory:
                profile = self.profiles_memory[user_id]
                for key, value in update_data.items():
                    if hasattr(profile, key):
                        setattr(profile, key, value)
                return profile
            return None
        
        return await self.with_fallback(db_operation, fallback_operation, user_id, update_data)
    
    async def add_event(self, user_id: str, event: UserEvent) -> bool:
        """Add user event."""
        async def db_operation(session: AsyncSession, user_id: str, event: UserEvent) -> bool:
            repo = UserProfileRepository(session)
            return await repo.add_event(user_id, event)
        
        async def fallback_operation(user_id: str, event: UserEvent) -> bool:
            # In fallback mode, just update the profile timestamp
            if user_id in self.profiles_memory:
                profile = self.profiles_memory[user_id]
                profile.last_updated = event.timestamp
                return True
            return False
        
        return await self.with_fallback(db_operation, fallback_operation, user_id, event)


class ImpressionService(DatabaseService):
    """Impression service with database persistence and fallback."""
    
    def __init__(self, fallback_storage: Optional[Dict[str, Impression]] = None):
        super().__init__()
        self.impressions_memory = fallback_storage or {}
    
    async def create_impression(self, impression: Impression) -> Impression:
        """Create impression record."""
        async def db_operation(session: AsyncSession, impression: Impression) -> Impression:
            repo = ImpressionRepository(session)
            return await repo.create(impression)
        
        async def fallback_operation(impression: Impression) -> Impression:
            self.impressions_memory[impression.id] = impression
            return impression
        
        return await self.with_fallback(db_operation, fallback_operation, impression)
    
    async def get_impressions_by_campaign(self, campaign_id: str, limit: int = 100, offset: int = 0) -> List[Impression]:
        """Get impressions by campaign."""
        async def db_operation(session: AsyncSession, campaign_id: str, limit: int, offset: int) -> List[Impression]:
            repo = ImpressionRepository(session)
            return await repo.get_by_campaign(campaign_id, limit, offset)
        
        async def fallback_operation(campaign_id: str, limit: int, offset: int) -> List[Impression]:
            impressions = [i for i in self.impressions_memory.values() if i.campaign_id == campaign_id]
            return impressions[offset:offset + limit]
        
        return await self.with_fallback(db_operation, fallback_operation, campaign_id, limit, offset)


class CampaignStatsService(DatabaseService):
    """Campaign statistics service with database persistence and fallback."""
    
    def __init__(self, fallback_storage: Optional[Dict[str, CampaignStats]] = None):
        super().__init__()
        self.stats_memory = fallback_storage or {}
    
    async def get_stats(self, campaign_id: str) -> Optional[CampaignStats]:
        """Get campaign statistics."""
        async def db_operation(session: AsyncSession, campaign_id: str) -> Optional[CampaignStats]:
            repo = CampaignStatsRepository(session)
            return await repo.get_by_campaign(campaign_id)
        
        async def fallback_operation(campaign_id: str) -> Optional[CampaignStats]:
            return self.stats_memory.get(campaign_id)
        
        return await self.with_fallback(db_operation, fallback_operation, campaign_id)
    
    async def update_stats(self, campaign_id: str, stats_update: Dict[str, Any]) -> bool:
        """Update campaign statistics."""
        async def db_operation(session: AsyncSession, campaign_id: str, stats_update: Dict[str, Any]) -> bool:
            repo = CampaignStatsRepository(session)
            return await repo.update_stats(campaign_id, stats_update)
        
        async def fallback_operation(campaign_id: str, stats_update: Dict[str, Any]) -> bool:
            if campaign_id in self.stats_memory:
                stats = self.stats_memory[campaign_id]
                for key, value in stats_update.items():
                    if hasattr(stats, key):
                        setattr(stats, key, value)
                return True
            else:
                # Create new stats
                from shared.models import CampaignStats
                stats = CampaignStats(campaign_id=campaign_id, **stats_update)
                self.stats_memory[campaign_id] = stats
                return True
        
        return await self.with_fallback(db_operation, fallback_operation, campaign_id, stats_update)


class AuctionResultService(DatabaseService):
    """Auction result service with database persistence and fallback."""
    
    def __init__(self, fallback_storage: Optional[Dict[str, AuctionResult]] = None):
        super().__init__()
        self.auctions_memory = fallback_storage or {}
    
    async def create_auction_result(self, auction_result: AuctionResult) -> AuctionResult:
        """Create auction result record."""
        async def db_operation(session: AsyncSession, auction_result: AuctionResult) -> AuctionResult:
            repo = AuctionResultRepository(session)
            return await repo.create(auction_result)
        
        async def fallback_operation(auction_result: AuctionResult) -> AuctionResult:
            self.auctions_memory[auction_result.auction_id] = auction_result
            return auction_result
        
        return await self.with_fallback(db_operation, fallback_operation, auction_result)
    
    async def get_recent_auctions(self, limit: int = 100) -> List[AuctionResult]:
        """Get recent auction results."""
        async def db_operation(session: AsyncSession, limit: int) -> List[AuctionResult]:
            repo = AuctionResultRepository(session)
            return await repo.get_recent_auctions(limit)
        
        async def fallback_operation(limit: int) -> List[AuctionResult]:
            auctions = list(self.auctions_memory.values())
            # Sort by timestamp descending
            auctions.sort(key=lambda x: x.timestamp, reverse=True)
            return auctions[:limit]
        
        return await self.with_fallback(db_operation, fallback_operation, limit)


# Global service instances
_campaign_service: Optional[CampaignService] = None
_user_profile_service: Optional[UserProfileService] = None
_impression_service: Optional[ImpressionService] = None
_campaign_stats_service: Optional[CampaignStatsService] = None
_auction_result_service: Optional[AuctionResultService] = None


def get_campaign_service() -> CampaignService:
    """Get global campaign service instance."""
    global _campaign_service
    if _campaign_service is None:
        _campaign_service = CampaignService()
    return _campaign_service


def get_user_profile_service() -> UserProfileService:
    """Get global user profile service instance."""
    global _user_profile_service
    if _user_profile_service is None:
        _user_profile_service = UserProfileService()
    return _user_profile_service


def get_impression_service() -> ImpressionService:
    """Get global impression service instance."""
    global _impression_service
    if _impression_service is None:
        _impression_service = ImpressionService()
    return _impression_service


def get_campaign_stats_service() -> CampaignStatsService:
    """Get global campaign stats service instance."""
    global _campaign_stats_service
    if _campaign_stats_service is None:
        _campaign_stats_service = CampaignStatsService()
    return _campaign_stats_service


def get_auction_result_service() -> AuctionResultService:
    """Get global auction result service instance."""
    global _auction_result_service
    if _auction_result_service is None:
        _auction_result_service = AuctionResultService()
    return _auction_result_service