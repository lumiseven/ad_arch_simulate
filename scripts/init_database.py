#!/usr/bin/env python3
"""
Database initialization script for the ad system.
Creates tables and sets up initial data.
"""

import asyncio
import logging
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from shared.database import init_database, create_tables_sync, check_database_health
from shared.config import get_config
from shared.utils import setup_logging

logger = setup_logging("database-init")


async def create_sample_data():
    """Create sample data for testing and demonstration."""
    from shared.database import AsyncSessionLocal
    from shared.database import (
        CampaignDB, UserProfileDB, CampaignStatsDB
    )
    from shared.utils import generate_id
    from datetime import datetime
    
    try:
        async with AsyncSessionLocal() as session:
            # Create sample campaigns
            sample_campaigns = [
                CampaignDB(
                    id=generate_id(),
                    name="Summer Sale Campaign",
                    advertiser_id="advertiser_001",
                    budget=10000.0,
                    spent=2500.0,
                    targeting={
                        "age_range": {"min_age": 18, "max_age": 35},
                        "interests": ["fashion", "shopping"],
                        "device_types": ["mobile", "desktop"]
                    },
                    creative={
                        "title": "Summer Sale - Up to 50% Off!",
                        "description": "Don't miss our biggest summer sale",
                        "image_url": "https://example.com/summer-sale.jpg",
                        "click_url": "https://example.com/summer-sale"
                    },
                    status="active"
                ),
                CampaignDB(
                    id=generate_id(),
                    name="Tech Product Launch",
                    advertiser_id="advertiser_002",
                    budget=25000.0,
                    spent=5000.0,
                    targeting={
                        "age_range": {"min_age": 25, "max_age": 45},
                        "interests": ["technology", "gadgets"],
                        "device_types": ["desktop", "tablet"]
                    },
                    creative={
                        "title": "Revolutionary New Tech Product",
                        "description": "Experience the future today",
                        "image_url": "https://example.com/tech-product.jpg",
                        "click_url": "https://example.com/tech-product"
                    },
                    status="active"
                ),
                CampaignDB(
                    id=generate_id(),
                    name="Food Delivery Promo",
                    advertiser_id="advertiser_003",
                    budget=5000.0,
                    spent=1200.0,
                    targeting={
                        "age_range": {"min_age": 20, "max_age": 40},
                        "interests": ["food", "delivery"],
                        "location": {"cities": ["New York", "Los Angeles", "Chicago"]}
                    },
                    creative={
                        "title": "Free Delivery on Your First Order",
                        "description": "Order now and get free delivery",
                        "image_url": "https://example.com/food-delivery.jpg",
                        "click_url": "https://example.com/food-delivery"
                    },
                    status="active"
                )
            ]
            
            for campaign in sample_campaigns:
                session.add(campaign)
            
            # Create sample user profiles
            sample_users = [
                UserProfileDB(
                    user_id="user_001",
                    demographics={
                        "age": 28,
                        "gender": "female",
                        "location": {"city": "New York", "country": "US"}
                    },
                    interests=["fashion", "shopping", "travel"],
                    behaviors=["frequent_shopper", "mobile_user"],
                    segments=["high_value_customer", "fashion_enthusiast"]
                ),
                UserProfileDB(
                    user_id="user_002",
                    demographics={
                        "age": 35,
                        "gender": "male",
                        "location": {"city": "San Francisco", "country": "US"}
                    },
                    interests=["technology", "gadgets", "gaming"],
                    behaviors=["early_adopter", "tech_savvy"],
                    segments=["tech_professional", "high_income"]
                ),
                UserProfileDB(
                    user_id="user_003",
                    demographics={
                        "age": 24,
                        "gender": "female",
                        "location": {"city": "Los Angeles", "country": "US"}
                    },
                    interests=["food", "cooking", "fitness"],
                    behaviors=["health_conscious", "social_media_active"],
                    segments=["young_professional", "health_focused"]
                )
            ]
            
            for user in sample_users:
                session.add(user)
            
            # Create campaign stats
            for campaign in sample_campaigns:
                stats = CampaignStatsDB(
                    campaign_id=campaign.id,
                    impressions=1000,
                    clicks=50,
                    conversions=5,
                    spend=campaign.spent,
                    revenue=campaign.spent * 1.2,  # 20% profit margin
                    ctr=0.05,  # 5% CTR
                    cpc=campaign.spent / 50 if campaign.spent > 0 else 0
                )
                session.add(stats)
            
            await session.commit()
            logger.info("Sample data created successfully")
            
    except Exception as e:
        logger.error(f"Failed to create sample data: {e}")
        raise


async def main():
    """Main initialization function."""
    logger.info("Starting database initialization...")
    
    try:
        # Initialize database tables
        logger.info("Creating database tables...")
        await init_database()
        
        # Check database health
        logger.info("Checking database connectivity...")
        is_healthy = await check_database_health()
        if not is_healthy:
            logger.error("Database health check failed")
            return False
        
        # Create sample data
        logger.info("Creating sample data...")
        await create_sample_data()
        
        logger.info("Database initialization completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False


def sync_init():
    """Synchronous initialization for migration scripts."""
    logger.info("Creating database tables (sync)...")
    try:
        create_tables_sync()
        logger.info("Database tables created successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to create tables: {e}")
        return False


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Initialize ad system database")
    parser.add_argument("--sync", action="store_true", help="Run synchronous initialization")
    parser.add_argument("--sample-data", action="store_true", help="Create sample data")
    args = parser.parse_args()
    
    if args.sync:
        success = sync_init()
    else:
        success = asyncio.run(main())
    
    sys.exit(0 if success else 1)