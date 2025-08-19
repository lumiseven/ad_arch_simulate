"""
Shared utilities for the ad system architecture.
Contains common functions and helpers used across services.
"""

import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
import httpx
from pydantic import BaseModel


def generate_id() -> str:
    """Generate a unique identifier."""
    return str(uuid.uuid4())


def get_current_timestamp() -> datetime:
    """Get current timestamp."""
    return datetime.now()


def setup_logging(service_name: str, level: str = "INFO") -> logging.Logger:
    """Set up logging for a service."""
    logger = logging.getLogger(service_name)
    logger.setLevel(getattr(logging, level.upper()))
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            f'%(asctime)s - {service_name} - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger


class APIClient:
    """HTTP client for service-to-service communication."""
    
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
    
    async def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make GET request."""
        url = f"{self.base_url}{endpoint}"
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    
    async def post(self, endpoint: str, data: Optional[BaseModel] = None, json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make POST request."""
        url = f"{self.base_url}{endpoint}"
        
        if data:
            json_data = data.model_dump()
        
        response = await self.client.post(url, json=json_data)
        response.raise_for_status()
        return response.json()
    
    async def put(self, endpoint: str, data: Optional[BaseModel] = None, json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make PUT request."""
        url = f"{self.base_url}{endpoint}"
        
        if data:
            json_data = data.model_dump()
        
        response = await self.client.put(url, json=json_data)
        response.raise_for_status()
        return response.json()
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


class ServiceConfig:
    """Configuration management for services."""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.host = "127.0.0.1"
        self.debug = True
        
        # Service port mapping
        self.port_mapping = {
            "ad-management": 8001,
            "dsp": 8002,
            "ssp": 8003,
            "ad-exchange": 8004,
            "dmp": 8005,
        }
        
        self.port = self.port_mapping.get(service_name, 8000)
    
    def get_service_url(self, service_name: str) -> str:
        """Get URL for another service."""
        port = self.port_mapping.get(service_name)
        if not port:
            raise ValueError(f"Unknown service: {service_name}")
        return f"http://{self.host}:{port}"


async def retry_async(func, max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Retry an async function with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            await asyncio.sleep(delay * (backoff ** attempt))


def log_rtb_step(logger: logging.Logger, step: str, data: Dict[str, Any]):
    """Log RTB workflow step with structured data."""
    logger.info(f"RTB Step: {step}")
    for key, value in data.items():
        logger.info(f"  {key}: {value}")


def validate_model_data(model_class: type[BaseModel], data: Dict[str, Any]) -> BaseModel:
    """Validate and create model instance from dictionary data."""
    try:
        return model_class.model_validate(data)
    except Exception as e:
        logger = logging.getLogger("validation")
        logger.error(f"Validation failed for {model_class.__name__}: {e}")
        raise


def serialize_model(model: BaseModel, exclude_none: bool = True) -> Dict[str, Any]:
    """Serialize model to dictionary with optional exclusion of None values."""
    return model.model_dump(exclude_none=exclude_none)


def create_error_response(error_code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create standardized error response."""
    from shared.models import ErrorResponse
    
    error = ErrorResponse(
        error_code=error_code,
        message=message,
        details=details or {}
    )
    return serialize_model(error)


def create_health_response(status: str = "healthy", details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create standardized health check response."""
    from shared.models import HealthCheck
    
    health = HealthCheck(
        status=status,
        details=details or {}
    )
    return serialize_model(health)


def validate_bid_request_data(data: Dict[str, Any]) -> bool:
    """Validate bid request data structure."""
    required_fields = ['id', 'user_id', 'ad_slot', 'device', 'geo']
    
    for field in required_fields:
        if field not in data:
            return False
    
    # Validate nested structures
    ad_slot_fields = ['id', 'width', 'height', 'position']
    if not all(field in data['ad_slot'] for field in ad_slot_fields):
        return False
    
    device_fields = ['type', 'os', 'browser', 'ip']
    if not all(field in data['device'] for field in device_fields):
        return False
    
    geo_fields = ['country', 'region', 'city']
    if not all(field in data['geo'] for field in geo_fields):
        return False
    
    return True


def calculate_auction_metrics(bids: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate auction metrics from bid responses."""
    if not bids:
        return {
            "total_bids": 0,
            "highest_bid": 0.0,
            "average_bid": 0.0,
            "bid_range": 0.0
        }
    
    prices = [bid.get('price', 0.0) for bid in bids]
    
    return {
        "total_bids": len(bids),
        "highest_bid": max(prices),
        "lowest_bid": min(prices),
        "average_bid": sum(prices) / len(prices),
        "bid_range": max(prices) - min(prices)
    }