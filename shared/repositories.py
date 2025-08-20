"""
Repository pattern implementation for data access layer.
Provides abstraction over database operations with error handling.
"""

import logging
from typing import List, Optional, Dict, Any, Type, TypeVar, Generic
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, update, delete, func, and_, or_
from sqlalchemy.exc import SQLAlchemyError

from shared.database import (
    CampaignDB, UserProfileDB, ImpressionDB, UserEventDB,
    CampaignStatsDB, AuctionResultDB, DatabaseError
)
from shared.models import (
    Campaign, UserProfile, Impression, UserEvent,
    CampaignStats, AuctionResult, CampaignStatus
)

logger = logging.getLogger(__name__)

T = TypeVar('T')
ModelType = TypeVar('ModelType')
DBModelType = TypeVar('DBModelType')


class BaseRepository(Generic[ModelType, DBModelType]):
    """Base repository class with common CRUD operations."""
    
    def __init__(self, session: AsyncSession, model_class: Type[ModelType], db_model_class: Type[DBModelType]):
        self.session = session
        self.model_class = model_class
        self.db_model_class = db_model_class
    
    async def create(self, obj: ModelType) -> ModelType:
        """Create a new record."""
        try:
            # Convert Pydantic model to SQLAlchemy model
            db_obj = self._to_db_model(obj)
            self.session.add(db_obj)
            await self.session.commit()
            await self.session.refresh(db_obj)
            return self._to_pydantic_model(db_obj)
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Failed to create {self.model_class.__name__}: {e}")
            raise DatabaseError(f"Failed to create record: {str(e)}", e)
    
    async def get_by_id(self, id_value: str) -> Optional[ModelType]:
        """Get record by ID."""
        try:
            # Determine the primary key column name
            pk_column = getattr(self.db_model_class, 'id', None)
            if pk_column is None:
                # Try common alternatives
                for attr_name in ['user_id', 'campaign_id', 'event_id', 'auction_id']:
                    if hasattr(self.db_model_class, attr_name):
                        pk_column = getattr(self.db_model_class, attr_name)
                        break
            
            if pk_column is None:
                raise DatabaseError("No primary key column found")
            
            stmt = select(self.db_model_class).where(pk_column == id_value)
            result = await self.session.execute(stmt)
            db_obj = result.scalar_one_or_none()
            
            if db_obj is None:
                return None
            
            return self._to_pydantic_model(db_obj)
        except SQLAlchemyError as e:
            logger.error(f"Failed to get {self.model_class.__name__} by ID {id_value}: {e}")
            raise DatabaseError(f"Failed to get record: {str(e)}", e)
    
    async def update(self, id_value: str, update_data: Dict[str, Any]) -> Optional[ModelType]:
        """Update record by ID."""
        try:
            # Get primary key column
            pk_column = getattr(self.db_model_class, 'id', None)
            if pk_column is None:
                for attr_name in ['user_id', 'campaign_id', 'event_id', 'auction_id']:
                    if hasattr(self.db_model_class, attr_name):
                        pk_column = getattr(self.db_model_class, attr_name)
                        break
            
            if pk_column is None:
                raise DatabaseError("No primary key column found")
            
            # Add updated_at if the model has it
            if hasattr(self.db_model_class, 'updated_at'):
                update_data['updated_at'] = datetime.now()
            
            stmt = (
                update(self.db_model_class)
                .where(pk_column == id_value)
                .values(**update_data)
                .returning(self.db_model_class)
            )
            
            result = await self.session.execute(stmt)
            await self.session.commit()
            
            db_obj = result.scalar_one_or_none()
            if db_obj is None:
                return None
            
            return self._to_pydantic_model(db_obj)
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Failed to update {self.model_class.__name__} {id_value}: {e}")
            raise DatabaseError(f"Failed to update record: {str(e)}", e)
    
    async def delete(self, id_value: str) -> bool:
        """Delete record by ID."""
        try:
            # Get primary key column
            pk_column = getattr(self.db_model_class, 'id', None)
            if pk_column is None:
                for attr_name in ['user_id', 'campaign_id', 'event_id', 'auction_id']:
                    if hasattr(self.db_model_class, attr_name):
                        pk_column = getattr(self.db_model_class, attr_name)
                        break
            
            if pk_column is None:
                raise DatabaseError("No primary key column found")
            
            stmt = delete(self.db_model_class).where(pk_column == id_value)
            result = await self.session.execute(stmt)
            await self.session.commit()
            
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Failed to delete {self.model_class.__name__} {id_value}: {e}")
            raise DatabaseError(f"Failed to delete record: {str(e)}", e)
    
    async def list_all(self, limit: int = 100, offset: int = 0) -> List[ModelType]:
        """List all records with pagination."""
        try:
            stmt = select(self.db_model_class).limit(limit).offset(offset)
            result = await self.session.execute(stmt)
            db_objs = result.scalars().all()
            
            return [self._to_pydantic_model(db_obj) for db_obj in db_objs]
        except SQLAlchemyError as e:
            logger.error(f"Failed to list {self.model_class.__name__}: {e}")
            raise DatabaseError(f"Failed to list records: {str(e)}", e)
    
    def _to_db_model(self, obj: ModelType) -> DBModelType:
        """Convert Pydantic model to SQLAlchemy model."""
        # This is a basic implementation - override in subclasses for complex conversions
        data = obj.model_dump() if hasattr(obj, 'model_dump') else obj.dict()
        return self.db_model_class(**data)
    
    def _to_pydantic_model(self, db_obj: DBModelType) -> ModelType:
        """Convert SQLAlchemy model to Pydantic model."""
        # This is a basic implementation - override in subclasses for complex conversions
        data = {}
        for column in self.db_model_class.__table__.columns:
            value = getattr(db_obj, column.name)
            data[column.name] = value
        return self.model_class(**data)


class CampaignRepository(BaseRepository[Campaign, CampaignDB]):
    """Repository for campaign operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(session, Campaign, CampaignDB)
    
    async def get_by_advertiser(self, advertiser_id: str, limit: int = 100, offset: int = 0) -> List[Campaign]:
        """Get campaigns by advertiser ID."""
        try:
            stmt = (
                select(CampaignDB)
                .where(CampaignDB.advertiser_id == advertiser_id)
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            db_objs = result.scalars().all()
            
            return [self._to_pydantic_model(db_obj) for db_obj in db_objs]
        except SQLAlchemyError as e:
            logger.error(f"Failed to get campaigns by advertiser {advertiser_id}: {e}")
            raise DatabaseError(f"Failed to get campaigns: {str(e)}", e)
    
    async def get_by_status(self, status: CampaignStatus, limit: int = 100, offset: int = 0) -> List[Campaign]:
        """Get campaigns by status."""
        try:
            stmt = (
                select(CampaignDB)
                .where(CampaignDB.status == status.value)
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            db_objs = result.scalars().all()
            
            return [self._to_pydantic_model(db_obj) for db_obj in db_objs]
        except SQLAlchemyError as e:
            logger.error(f"Failed to get campaigns by status {status}: {e}")
            raise DatabaseError(f"Failed to get campaigns: {str(e)}", e)
    
    async def update_spend(self, campaign_id: str, amount: float) -> bool:
        """Update campaign spend amount."""
        try:
            # First check if the campaign exists and has sufficient budget
            campaign = await self.get_by_id(campaign_id)
            if not campaign:
                return False
            
            new_spent = campaign.spent + amount
            if new_spent > campaign.budget:
                logger.warning(f"Spend amount {new_spent} exceeds budget {campaign.budget} for campaign {campaign_id}")
                return False
            
            # Update the spend
            await self.update(campaign_id, {"spent": new_spent})
            return True
        except Exception as e:
            logger.error(f"Failed to update spend for campaign {campaign_id}: {e}")
            return False
    
    async def get_active_campaigns(self) -> List[Campaign]:
        """Get all active campaigns."""
        return await self.get_by_status(CampaignStatus.ACTIVE)


class UserProfileRepository(BaseRepository[UserProfile, UserProfileDB]):
    """Repository for user profile operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(session, UserProfile, UserProfileDB)
    
    async def get_by_id(self, user_id: str) -> Optional[UserProfile]:
        """Get user profile by user ID."""
        try:
            stmt = select(UserProfileDB).where(UserProfileDB.user_id == user_id)
            result = await self.session.execute(stmt)
            db_obj = result.scalar_one_or_none()
            
            if db_obj is None:
                return None
            
            return self._to_pydantic_model(db_obj)
        except SQLAlchemyError as e:
            logger.error(f"Failed to get user profile {user_id}: {e}")
            raise DatabaseError(f"Failed to get user profile: {str(e)}", e)
    
    async def get_by_segment(self, segment: str, limit: int = 100, offset: int = 0) -> List[UserProfile]:
        """Get users by segment."""
        try:
            # Note: This is a simplified query. In production, you might want to use JSON operators
            stmt = (
                select(UserProfileDB)
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            db_objs = result.scalars().all()
            
            # Filter by segment in Python (in production, use database JSON operators)
            filtered_users = []
            for db_obj in db_objs:
                if segment in (db_obj.segments or []):
                    filtered_users.append(self._to_pydantic_model(db_obj))
            
            return filtered_users
        except SQLAlchemyError as e:
            logger.error(f"Failed to get users by segment {segment}: {e}")
            raise DatabaseError(f"Failed to get users: {str(e)}", e)
    
    async def add_event(self, user_id: str, event: UserEvent) -> bool:
        """Add user event and update profile."""
        try:
            # Create the event
            event_repo = UserEventRepository(self.session)
            await event_repo.create(event)
            
            # Update user profile last_updated timestamp
            await self.update(user_id, {"last_updated": datetime.now()})
            
            return True
        except Exception as e:
            logger.error(f"Failed to add event for user {user_id}: {e}")
            return False


class ImpressionRepository(BaseRepository[Impression, ImpressionDB]):
    """Repository for impression operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(session, Impression, ImpressionDB)
    
    async def get_by_campaign(self, campaign_id: str, limit: int = 100, offset: int = 0) -> List[Impression]:
        """Get impressions by campaign ID."""
        try:
            stmt = (
                select(ImpressionDB)
                .where(ImpressionDB.campaign_id == campaign_id)
                .order_by(ImpressionDB.timestamp.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            db_objs = result.scalars().all()
            
            return [self._to_pydantic_model(db_obj) for db_obj in db_objs]
        except SQLAlchemyError as e:
            logger.error(f"Failed to get impressions by campaign {campaign_id}: {e}")
            raise DatabaseError(f"Failed to get impressions: {str(e)}", e)
    
    async def get_by_user(self, user_id: str, limit: int = 100, offset: int = 0) -> List[Impression]:
        """Get impressions by user ID."""
        try:
            stmt = (
                select(ImpressionDB)
                .where(ImpressionDB.user_id == user_id)
                .order_by(ImpressionDB.timestamp.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            db_objs = result.scalars().all()
            
            return [self._to_pydantic_model(db_obj) for db_obj in db_objs]
        except SQLAlchemyError as e:
            logger.error(f"Failed to get impressions by user {user_id}: {e}")
            raise DatabaseError(f"Failed to get impressions: {str(e)}", e)


class UserEventRepository(BaseRepository[UserEvent, UserEventDB]):
    """Repository for user event operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(session, UserEvent, UserEventDB)
    
    async def get_by_user(self, user_id: str, limit: int = 100, offset: int = 0) -> List[UserEvent]:
        """Get events by user ID."""
        try:
            stmt = (
                select(UserEventDB)
                .where(UserEventDB.user_id == user_id)
                .order_by(UserEventDB.timestamp.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            db_objs = result.scalars().all()
            
            return [self._to_pydantic_model(db_obj) for db_obj in db_objs]
        except SQLAlchemyError as e:
            logger.error(f"Failed to get events by user {user_id}: {e}")
            raise DatabaseError(f"Failed to get events: {str(e)}", e)
    
    async def get_by_type(self, event_type: str, limit: int = 100, offset: int = 0) -> List[UserEvent]:
        """Get events by type."""
        try:
            stmt = (
                select(UserEventDB)
                .where(UserEventDB.event_type == event_type)
                .order_by(UserEventDB.timestamp.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            db_objs = result.scalars().all()
            
            return [self._to_pydantic_model(db_obj) for db_obj in db_objs]
        except SQLAlchemyError as e:
            logger.error(f"Failed to get events by type {event_type}: {e}")
            raise DatabaseError(f"Failed to get events: {str(e)}", e)


class CampaignStatsRepository(BaseRepository[CampaignStats, CampaignStatsDB]):
    """Repository for campaign statistics operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(session, CampaignStats, CampaignStatsDB)
    
    async def get_by_campaign(self, campaign_id: str) -> Optional[CampaignStats]:
        """Get stats by campaign ID."""
        try:
            stmt = select(CampaignStatsDB).where(CampaignStatsDB.campaign_id == campaign_id)
            result = await self.session.execute(stmt)
            db_obj = result.scalar_one_or_none()
            
            if db_obj is None:
                return None
            
            return self._to_pydantic_model(db_obj)
        except SQLAlchemyError as e:
            logger.error(f"Failed to get stats for campaign {campaign_id}: {e}")
            raise DatabaseError(f"Failed to get stats: {str(e)}", e)
    
    async def update_stats(self, campaign_id: str, stats_update: Dict[str, Any]) -> bool:
        """Update campaign statistics."""
        try:
            # Calculate derived metrics
            if 'impressions' in stats_update and 'clicks' in stats_update:
                impressions = stats_update['impressions']
                clicks = stats_update['clicks']
                stats_update['ctr'] = clicks / impressions if impressions > 0 else 0
            
            if 'spend' in stats_update and 'clicks' in stats_update:
                spend = stats_update['spend']
                clicks = stats_update['clicks']
                stats_update['cpc'] = spend / clicks if clicks > 0 else 0
            
            stats_update['updated_at'] = datetime.now()
            
            stmt = (
                update(CampaignStatsDB)
                .where(CampaignStatsDB.campaign_id == campaign_id)
                .values(**stats_update)
            )
            
            result = await self.session.execute(stmt)
            await self.session.commit()
            
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Failed to update stats for campaign {campaign_id}: {e}")
            raise DatabaseError(f"Failed to update stats: {str(e)}", e)


class AuctionResultRepository(BaseRepository[AuctionResult, AuctionResultDB]):
    """Repository for auction result operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(session, AuctionResult, AuctionResultDB)
    
    async def get_recent_auctions(self, limit: int = 100) -> List[AuctionResult]:
        """Get recent auction results."""
        try:
            stmt = (
                select(AuctionResultDB)
                .order_by(AuctionResultDB.timestamp.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            db_objs = result.scalars().all()
            
            return [self._to_pydantic_model(db_obj) for db_obj in db_objs]
        except SQLAlchemyError as e:
            logger.error(f"Failed to get recent auctions: {e}")
            raise DatabaseError(f"Failed to get auctions: {str(e)}", e)