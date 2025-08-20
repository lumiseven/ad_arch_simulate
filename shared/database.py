"""
广告系统的数据库配置和工具模块

提供SQLAlchemy数据库模型和会话管理功能，支持异步数据库操作。

核心功能：
- 数据库连接配置和会话管理
- SQLAlchemy ORM模型定义
- 异步数据库操作支持
- 数据库健康检查
- SQLite性能优化配置

数据库模型：
- CampaignDB: 广告活动数据表
- UserProfileDB: 用户画像数据表
- ImpressionDB: 广告展示记录表
- UserEventDB: 用户行为事件表
- CampaignStatsDB: 广告活动统计表
- AuctionResultDB: 竞价结果记录表

工具函数：
- get_db(): 数据库会话依赖注入
- init_database(): 初始化数据库表
- check_database_health(): 数据库健康检查
- safe_database_operation(): 安全数据库操作包装

支持SQLite和PostgreSQL数据库，包含完整的索引优化。
"""

import os
import logging
from typing import AsyncGenerator, Optional
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Integer, DateTime, Text, Boolean,
    ForeignKey, Index, create_engine, event
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.sql import func
import json

logger = logging.getLogger(__name__)

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ad_system.db")
SYNC_DATABASE_URL = os.getenv("SYNC_DATABASE_URL", "sqlite:///./ad_system.db")

# Create async engine
async_engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("DATABASE_ECHO", "false").lower() == "true",
    future=True,
    pool_pre_ping=True,
)

# Create sync engine for migrations
sync_engine = create_engine(
    SYNC_DATABASE_URL,
    echo=os.getenv("DATABASE_ECHO", "false").lower() == "true",
    future=True,
)

# Create session makers
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

SessionLocal = sessionmaker(
    sync_engine,
    expire_on_commit=False
)

# Base class for all models
Base = declarative_base()


class CampaignDB(Base):
    """Campaign database model."""
    __tablename__ = "campaigns"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    advertiser_id = Column(String, nullable=False, index=True)
    budget = Column(Float, nullable=False)
    spent = Column(Float, default=0.0, nullable=False)
    targeting = Column(JSON, default=lambda: {})
    creative = Column(JSON, default=lambda: {})
    status = Column(String(20), default="draft", nullable=False, index=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    

    
    # Indexes
    __table_args__ = (
        Index('idx_campaigns_advertiser_status', 'advertiser_id', 'status'),
        Index('idx_campaigns_created_at', 'created_at'),
    )


class UserProfileDB(Base):
    """User profile database model."""
    __tablename__ = "user_profiles"
    
    user_id = Column(String, primary_key=True, index=True)
    demographics = Column(JSON, default=lambda: {})
    interests = Column(JSON, default=lambda: [])
    behaviors = Column(JSON, default=lambda: [])
    segments = Column(JSON, default=lambda: [])
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    

    
    # Indexes
    __table_args__ = (
        Index('idx_user_profiles_last_updated', 'last_updated'),
    )


class ImpressionDB(Base):
    """Impression database model."""
    __tablename__ = "impressions"
    
    id = Column(String, primary_key=True, index=True)
    campaign_id = Column(String, nullable=False, index=True)  # Remove FK constraint for now
    user_id = Column(String, nullable=False, index=True)  # Remove FK constraint for now
    price = Column(Float, nullable=False)
    revenue = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=func.now(), nullable=False, index=True)
    
    # Additional fields for RTB data
    request_id = Column(String, index=True)
    dsp_id = Column(String, index=True)
    ad_slot_data = Column(JSON, default=lambda: {})
    device_data = Column(JSON, default=lambda: {})
    geo_data = Column(JSON, default=lambda: {})
    
    # Indexes
    __table_args__ = (
        Index('idx_impressions_campaign_timestamp', 'campaign_id', 'timestamp'),
        Index('idx_impressions_user_timestamp', 'user_id', 'timestamp'),
        Index('idx_impressions_dsp_timestamp', 'dsp_id', 'timestamp'),
    )


class UserEventDB(Base):
    """User event database model."""
    __tablename__ = "user_events"
    
    event_id = Column(String, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)  # Remove FK constraint for now
    event_type = Column(String(50), nullable=False, index=True)
    event_data = Column(JSON, default=lambda: {})
    timestamp = Column(DateTime, default=func.now(), nullable=False, index=True)
    
    # Indexes
    __table_args__ = (
        Index('idx_user_events_type_timestamp', 'event_type', 'timestamp'),
        Index('idx_user_events_user_type', 'user_id', 'event_type'),
    )


class CampaignStatsDB(Base):
    """Campaign statistics database model."""
    __tablename__ = "campaign_stats"
    
    campaign_id = Column(String, primary_key=True, index=True)  # Remove FK constraint for now
    impressions = Column(Integer, default=0, nullable=False)
    clicks = Column(Integer, default=0, nullable=False)
    conversions = Column(Integer, default=0, nullable=False)
    spend = Column(Float, default=0.0, nullable=False)
    revenue = Column(Float, default=0.0, nullable=False)
    ctr = Column(Float, default=0.0, nullable=False)
    cpc = Column(Float, default=0.0, nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


class AuctionResultDB(Base):
    """Auction result database model."""
    __tablename__ = "auction_results"
    
    auction_id = Column(String, primary_key=True, index=True)
    request_id = Column(String, nullable=False, index=True)
    winning_bid_data = Column(JSON)
    all_bids_data = Column(JSON, default=lambda: [])
    auction_price = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=func.now(), nullable=False, index=True)
    
    # Additional auction metadata
    dsp_count = Column(Integer, default=0)
    processing_time_ms = Column(Float)
    
    # Indexes
    __table_args__ = (
        Index('idx_auction_results_timestamp', 'timestamp'),
        Index('idx_auction_results_request_id', 'request_id'),
    )


# Database session dependency
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for dependency injection."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Database session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


# Database utilities
async def init_database():
    """Initialize database tables."""
    try:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


async def check_database_health() -> bool:
    """Check database connectivity and health."""
    try:
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            # Simple query to test connectivity
            result = await session.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


def create_tables_sync():
    """Create tables synchronously (for migrations)."""
    try:
        Base.metadata.create_all(bind=sync_engine)
        logger.info("Database tables created successfully (sync)")
    except Exception as e:
        logger.error(f"Failed to create tables: {e}")
        raise


# SQLite specific optimizations
@event.listens_for(sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Set SQLite pragmas for better performance."""
    if "sqlite" in str(sync_engine.url):
        cursor = dbapi_connection.cursor()
        # Enable foreign key constraints
        cursor.execute("PRAGMA foreign_keys=ON")
        # Set journal mode to WAL for better concurrency
        cursor.execute("PRAGMA journal_mode=WAL")
        # Set synchronous mode to NORMAL for better performance
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Set cache size (negative value means KB)
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
        # Set temp store to memory
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()


@event.listens_for(async_engine.sync_engine, "connect")
def set_sqlite_pragma_async(dbapi_connection, connection_record):
    """Set SQLite pragmas for async engine."""
    if "sqlite" in str(async_engine.url):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()


# Data access layer utilities
class DatabaseError(Exception):
    """Custom database error."""
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        self.message = message
        self.original_error = original_error
        super().__init__(self.message)


async def safe_database_operation(operation, *args, **kwargs):
    """Safely execute database operation with error handling."""
    try:
        return await operation(*args, **kwargs)
    except Exception as e:
        logger.error(f"Database operation failed: {e}")
        raise DatabaseError(f"Database operation failed: {str(e)}", e)


def convert_json_fields(data: dict) -> dict:
    """Convert JSON fields to proper format for database storage."""
    converted = {}
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            converted[key] = json.dumps(value) if isinstance(value, (dict, list)) else value
        else:
            converted[key] = value
    return converted


def parse_json_fields(data: dict, json_fields: list) -> dict:
    """Parse JSON fields from database."""
    parsed = data.copy()
    for field in json_fields:
        if field in parsed and isinstance(parsed[field], str):
            try:
                parsed[field] = json.loads(parsed[field])
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Failed to parse JSON field {field}: {parsed[field]}")
                parsed[field] = {}
    return parsed