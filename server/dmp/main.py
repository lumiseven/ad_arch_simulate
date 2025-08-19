"""
Data Management Platform (DMP) Service

This service manages user profiles, behavior data collection, and user segmentation.
It provides APIs for storing and querying user data to support targeted advertising.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
import uvicorn

from shared.models import (
    UserProfile, 
    UserEvent, 
    ErrorResponse, 
    HealthCheck
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DMP")

# FastAPI application
app = FastAPI(
    title="Data Management Platform (DMP)",
    description="User profile and behavior data management service",
    version="0.1.0"
)

# In-memory storage for demonstration (in production, use a proper database)
user_profiles: Dict[str, UserProfile] = {}
user_events: Dict[str, List[UserEvent]] = {}
user_segments: Dict[str, List[str]] = {
    "high_value": [],
    "frequent_buyers": [],
    "mobile_users": [],
    "young_adults": [],
    "tech_enthusiasts": []
}

@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint."""
    return HealthCheck(
        status="healthy",
        details={
            "total_profiles": len(user_profiles),
            "total_events": sum(len(events) for events in user_events.values()),
            "segments": {name: len(users) for name, users in user_segments.items()}
        }
    )

@app.get("/user/{user_id}/profile", response_model=UserProfile)
async def get_user_profile(user_id: str):
    """Get user profile by user ID."""
    logger.info(f"Retrieving profile for user: {user_id}")
    
    if user_id not in user_profiles:
        logger.warning(f"Profile not found for user: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User profile not found for user_id: {user_id}"
        )
    
    profile = user_profiles[user_id]
    logger.info(f"Profile retrieved for user {user_id}: {len(profile.interests)} interests, {len(profile.behaviors)} behaviors")
    return profile

@app.put("/user/{user_id}/profile", response_model=UserProfile)
async def update_user_profile(user_id: str, profile_data: Dict[str, Any]):
    """Update or create user profile."""
    logger.info(f"Updating profile for user: {user_id}")
    
    try:
        # Get existing profile or create new one
        if user_id in user_profiles:
            existing_profile = user_profiles[user_id]
            # Merge with existing data
            demographics = {**existing_profile.demographics, **profile_data.get("demographics", {})}
            interests = list(set(existing_profile.interests + profile_data.get("interests", [])))
            behaviors = list(set(existing_profile.behaviors + profile_data.get("behaviors", [])))
            segments = list(set(existing_profile.segments + profile_data.get("segments", [])))
        else:
            demographics = profile_data.get("demographics", {})
            interests = profile_data.get("interests", [])
            behaviors = profile_data.get("behaviors", [])
            segments = profile_data.get("segments", [])
        
        # Create updated profile
        updated_profile = UserProfile(
            user_id=user_id,
            demographics=demographics,
            interests=interests,
            behaviors=behaviors,
            segments=segments,
            last_updated=datetime.now()
        )
        
        user_profiles[user_id] = updated_profile
        
        # Update segment memberships
        _update_segment_memberships(user_id, updated_profile)
        
        logger.info(f"Profile updated for user {user_id}: {len(interests)} interests, {len(behaviors)} behaviors")
        return updated_profile
        
    except Exception as e:
        logger.error(f"Error updating profile for user {user_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid profile data: {str(e)}"
        )

@app.post("/user/{user_id}/events", response_model=Dict[str, str])
async def record_user_event(user_id: str, event_data: Dict[str, Any]):
    """Record user behavior event."""
    logger.info(f"Recording event for user: {user_id}, type: {event_data.get('event_type')}")
    
    try:
        # Create event
        event = UserEvent(
            event_id=str(uuid.uuid4()),
            user_id=user_id,
            event_type=event_data["event_type"],
            event_data=event_data.get("event_data", {}),
            timestamp=datetime.now()
        )
        
        # Store event
        if user_id not in user_events:
            user_events[user_id] = []
        user_events[user_id].append(event)
        
        # Update user profile based on event
        await _update_profile_from_event(user_id, event)
        
        logger.info(f"Event recorded for user {user_id}: {event.event_type}")
        return {"message": "Event recorded successfully", "event_id": event.event_id}
        
    except KeyError as e:
        logger.error(f"Missing required field in event data: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required field: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error recording event for user {user_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid event data: {str(e)}"
        )

@app.get("/user/{user_id}/events")
async def get_user_events(user_id: str, limit: int = 100):
    """Get user behavior events."""
    logger.info(f"Retrieving events for user: {user_id}, limit: {limit}")
    
    if user_id not in user_events:
        return {"user_id": user_id, "events": []}
    
    events = user_events[user_id]
    # Return most recent events first
    recent_events = sorted(events, key=lambda x: x.timestamp, reverse=True)[:limit]
    
    logger.info(f"Retrieved {len(recent_events)} events for user {user_id}")
    return {
        "user_id": user_id,
        "events": [event.model_dump() for event in recent_events],
        "total_events": len(events)
    }

@app.get("/segments", response_model=Dict[str, List[str]])
async def get_segments():
    """Get all user segments."""
    logger.info("Retrieving all user segments")
    return user_segments

@app.get("/segments/{segment_name}")
async def get_segment_users(segment_name: str):
    """Get users in a specific segment."""
    logger.info(f"Retrieving users in segment: {segment_name}")
    
    if segment_name not in user_segments:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Segment not found: {segment_name}"
        )
    
    users = user_segments[segment_name]
    logger.info(f"Found {len(users)} users in segment {segment_name}")
    return {
        "segment_name": segment_name,
        "users": users,
        "count": len(users)
    }

@app.post("/segments/{segment_name}/users/{user_id}")
async def add_user_to_segment(segment_name: str, user_id: str):
    """Add user to a segment."""
    logger.info(f"Adding user {user_id} to segment {segment_name}")
    
    if segment_name not in user_segments:
        user_segments[segment_name] = []
    
    if user_id not in user_segments[segment_name]:
        user_segments[segment_name].append(user_id)
        
        # Update user profile
        if user_id in user_profiles:
            profile = user_profiles[user_id]
            if segment_name not in profile.segments:
                profile.segments.append(segment_name)
                profile.last_updated = datetime.now()
    
    logger.info(f"User {user_id} added to segment {segment_name}")
    return {"message": f"User {user_id} added to segment {segment_name}"}

@app.delete("/segments/{segment_name}/users/{user_id}")
async def remove_user_from_segment(segment_name: str, user_id: str):
    """Remove user from a segment."""
    logger.info(f"Removing user {user_id} from segment {segment_name}")
    
    if segment_name in user_segments and user_id in user_segments[segment_name]:
        user_segments[segment_name].remove(user_id)
        
        # Update user profile
        if user_id in user_profiles:
            profile = user_profiles[user_id]
            if segment_name in profile.segments:
                profile.segments.remove(segment_name)
                profile.last_updated = datetime.now()
    
    logger.info(f"User {user_id} removed from segment {segment_name}")
    return {"message": f"User {user_id} removed from segment {segment_name}"}

async def _update_profile_from_event(user_id: str, event: UserEvent):
    """Update user profile based on behavior event."""
    # Get or create profile
    if user_id not in user_profiles:
        user_profiles[user_id] = UserProfile(user_id=user_id)
    
    profile = user_profiles[user_id]
    
    # Add behavior tags based on event type
    behavior_mapping = {
        "click": "clicker",
        "view": "viewer", 
        "purchase": "buyer",
        "signup": "new_user",
        "page_visit": "browser",
        "search": "searcher"
    }
    
    if event.event_type in behavior_mapping:
        behavior_tag = behavior_mapping[event.event_type]
        if behavior_tag not in profile.behaviors:
            profile.behaviors.append(behavior_tag)
    
    # Add interest tags based on event data
    if "category" in event.event_data:
        category = event.event_data["category"]
        if category not in profile.interests:
            profile.interests.append(category)
    
    # Update demographics from device info
    if "device_type" in event.event_data:
        profile.demographics["device_type"] = event.event_data["device_type"]
    
    profile.last_updated = datetime.now()
    
    # Update segment memberships
    _update_segment_memberships(user_id, profile)

def _update_segment_memberships(user_id: str, profile: UserProfile):
    """Update user segment memberships based on profile."""
    # High value users (have purchase behavior)
    if "buyer" in profile.behaviors:
        if user_id not in user_segments["high_value"]:
            user_segments["high_value"].append(user_id)
        if "high_value" not in profile.segments:
            profile.segments.append("high_value")
    
    # Frequent buyers (multiple purchase events)
    user_purchase_events = 0
    if user_id in user_events:
        user_purchase_events = len([e for e in user_events[user_id] if e.event_type == "purchase"])
    
    if user_purchase_events >= 3:
        if user_id not in user_segments["frequent_buyers"]:
            user_segments["frequent_buyers"].append(user_id)
        if "frequent_buyers" not in profile.segments:
            profile.segments.append("frequent_buyers")
    
    # Mobile users
    if profile.demographics.get("device_type") == "mobile":
        if user_id not in user_segments["mobile_users"]:
            user_segments["mobile_users"].append(user_id)
        if "mobile_users" not in profile.segments:
            profile.segments.append("mobile_users")
    
    # Young adults (age 18-35)
    age = profile.demographics.get("age")
    if age and 18 <= age <= 35:
        if user_id not in user_segments["young_adults"]:
            user_segments["young_adults"].append(user_id)
        if "young_adults" not in profile.segments:
            profile.segments.append("young_adults")
    
    # Tech enthusiasts (interested in technology)
    tech_interests = ["technology", "gadgets", "software", "electronics"]
    if any(interest in tech_interests for interest in profile.interests):
        if user_id not in user_segments["tech_enthusiasts"]:
            user_segments["tech_enthusiasts"].append(user_id)
        if "tech_enthusiasts" not in profile.segments:
            profile.segments.append("tech_enthusiasts")

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {str(exc)}")
    error_response = ErrorResponse(
        error_code="INTERNAL_ERROR",
        message="An internal error occurred",
        details={"error": str(exc)}
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response.model_dump()
    )

if __name__ == "__main__":
    logger.info("Starting DMP service on port 8005")
    uvicorn.run(app, host="0.0.0.0", port=8005)