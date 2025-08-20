"""
Shared utilities for the ad system architecture.
Contains common functions and helpers used across services.
"""

import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable
import httpx
from pydantic import BaseModel
import json
import time


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


class ServiceError(Exception):
    """Base exception for service communication errors."""
    
    def __init__(self, message: str, error_code: str = "SERVICE_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}


class ServiceUnavailableError(ServiceError):
    """Exception raised when a service is unavailable."""
    
    def __init__(self, service_name: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            f"Service {service_name} is unavailable",
            "SERVICE_UNAVAILABLE",
            details
        )
        self.service_name = service_name


class ServiceTimeoutError(ServiceError):
    """Exception raised when a service request times out."""
    
    def __init__(self, service_name: str, timeout: float, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            f"Service {service_name} request timed out after {timeout}s",
            "SERVICE_TIMEOUT",
            details
        )
        self.service_name = service_name
        self.timeout = timeout


class APIClient:
    """Enhanced HTTP client for service-to-service communication with retry logic."""
    
    def __init__(self, base_url: str, timeout: float = 5.0, max_retries: int = 3, 
                 retry_delay: float = 1.0, retry_backoff: float = 2.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.retry_backoff = retry_backoff
        self.client = httpx.AsyncClient(timeout=timeout)
        self.service_name = self._extract_service_name(base_url)
        self.logger = setup_logging(f"api-client-{self.service_name}")
    
    def _extract_service_name(self, base_url: str) -> str:
        """Extract service name from base URL."""
        # Extract from port mapping or URL path
        port_to_service = {
            "8001": "ad-management",
            "8002": "dsp", 
            "8003": "ssp",
            "8004": "ad-exchange",
            "8005": "dmp"
        }
        
        for port, service in port_to_service.items():
            if port in base_url:
                return service
        
        return "unknown"
    
    async def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, 
                  retries: Optional[int] = None) -> Dict[str, Any]:
        """Make GET request with retry logic."""
        return await self._request_with_retry("GET", endpoint, params=params, retries=retries)
    
    async def post(self, endpoint: str, data: Optional[BaseModel] = None, 
                   json_data: Optional[Dict[str, Any]] = None, 
                   retries: Optional[int] = None) -> Dict[str, Any]:
        """Make POST request with retry logic."""
        if data:
            json_data = data.model_dump()
        return await self._request_with_retry("POST", endpoint, json_data=json_data, retries=retries)
    
    async def put(self, endpoint: str, data: Optional[BaseModel] = None, 
                  json_data: Optional[Dict[str, Any]] = None,
                  retries: Optional[int] = None) -> Dict[str, Any]:
        """Make PUT request with retry logic."""
        if data:
            json_data = data.model_dump()
        return await self._request_with_retry("PUT", endpoint, json_data=json_data, retries=retries)
    
    async def delete(self, endpoint: str, retries: Optional[int] = None) -> Dict[str, Any]:
        """Make DELETE request with retry logic."""
        return await self._request_with_retry("DELETE", endpoint, retries=retries)
    
    async def _request_with_retry(self, method: str, endpoint: str, 
                                  params: Optional[Dict[str, Any]] = None,
                                  json_data: Optional[Dict[str, Any]] = None,
                                  retries: Optional[int] = None) -> Dict[str, Any]:
        """Make HTTP request with retry logic."""
        max_retries = retries if retries is not None else self.max_retries
        url = f"{self.base_url}{endpoint}"
        
        last_exception = None
        
        for attempt in range(max_retries + 1):
            try:
                self.logger.debug(f"Attempting {method} {url} (attempt {attempt + 1}/{max_retries + 1})")
                
                # Make the request
                if method == "GET":
                    response = await self.client.get(url, params=params)
                elif method == "POST":
                    response = await self.client.post(url, json=json_data)
                elif method == "PUT":
                    response = await self.client.put(url, json=json_data)
                elif method == "DELETE":
                    response = await self.client.delete(url)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                # Check for HTTP errors
                if response.status_code >= 500:
                    # Server error - retry
                    raise httpx.HTTPStatusError(
                        f"Server error {response.status_code}",
                        request=response.request,
                        response=response
                    )
                elif response.status_code >= 400:
                    # Client error - don't retry
                    response.raise_for_status()
                
                # Success
                self.logger.debug(f"Successful {method} {url} (status: {response.status_code})")
                
                try:
                    return response.json()
                except json.JSONDecodeError:
                    # Return empty dict for non-JSON responses
                    return {}
                
            except httpx.TimeoutException as e:
                last_exception = ServiceTimeoutError(
                    self.service_name, 
                    self.timeout,
                    {"attempt": attempt + 1, "url": url}
                )
                self.logger.warning(f"Timeout on {method} {url} (attempt {attempt + 1}): {e}")
                
            except httpx.ConnectError as e:
                last_exception = ServiceUnavailableError(
                    self.service_name,
                    {"attempt": attempt + 1, "url": url, "error": str(e)}
                )
                self.logger.warning(f"Connection error on {method} {url} (attempt {attempt + 1}): {e}")
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    # Server error - retry
                    last_exception = ServiceError(
                        f"Server error from {self.service_name}",
                        "SERVER_ERROR",
                        {"status_code": e.response.status_code, "attempt": attempt + 1, "url": url}
                    )
                    self.logger.warning(f"Server error on {method} {url} (attempt {attempt + 1}): {e}")
                else:
                    # Client error - don't retry
                    try:
                        error_data = e.response.json()
                        raise ServiceError(
                            error_data.get("message", f"Client error {e.response.status_code}"),
                            error_data.get("error_code", "CLIENT_ERROR"),
                            error_data.get("details", {"status_code": e.response.status_code})
                        )
                    except json.JSONDecodeError:
                        raise ServiceError(
                            f"Client error {e.response.status_code}",
                            "CLIENT_ERROR",
                            {"status_code": e.response.status_code}
                        )
            
            except Exception as e:
                last_exception = ServiceError(
                    f"Unexpected error communicating with {self.service_name}: {str(e)}",
                    "COMMUNICATION_ERROR",
                    {"attempt": attempt + 1, "url": url, "error": str(e)}
                )
                self.logger.error(f"Unexpected error on {method} {url} (attempt {attempt + 1}): {e}")
            
            # Wait before retry (except on last attempt)
            if attempt < max_retries:
                delay = self.retry_delay * (self.retry_backoff ** attempt)
                self.logger.debug(f"Waiting {delay}s before retry...")
                await asyncio.sleep(delay)
        
        # All retries exhausted
        if last_exception:
            raise last_exception
        else:
            raise ServiceError(f"All retries exhausted for {method} {url}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check service health."""
        try:
            return await self.get("/health", retries=1)
        except Exception as e:
            self.logger.error(f"Health check failed for {self.service_name}: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "service": self.service_name
            }
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


class ServiceRegistry:
    """Simple service registry for service discovery."""
    
    def __init__(self):
        self._services: Dict[str, Dict[str, Any]] = {}
        self._logger = setup_logging("service-registry")
    
    def register_service(self, service_name: str, host: str, port: int, 
                        health_endpoint: str = "/health", metadata: Optional[Dict[str, Any]] = None):
        """Register a service in the registry."""
        service_info = {
            "name": service_name,
            "host": host,
            "port": port,
            "url": f"http://{host}:{port}",
            "health_endpoint": health_endpoint,
            "metadata": metadata or {},
            "registered_at": datetime.now(),
            "last_health_check": None,
            "status": "unknown"
        }
        
        self._services[service_name] = service_info
        self._logger.info(f"Registered service {service_name} at {service_info['url']}")
    
    def unregister_service(self, service_name: str):
        """Unregister a service from the registry."""
        if service_name in self._services:
            del self._services[service_name]
            self._logger.info(f"Unregistered service {service_name}")
    
    def get_service(self, service_name: str) -> Optional[Dict[str, Any]]:
        """Get service information by name."""
        return self._services.get(service_name)
    
    def get_service_url(self, service_name: str) -> str:
        """Get service URL by name."""
        service = self.get_service(service_name)
        if not service:
            raise ValueError(f"Service {service_name} not found in registry")
        return service["url"]
    
    def list_services(self) -> Dict[str, Dict[str, Any]]:
        """List all registered services."""
        return self._services.copy()
    
    def get_healthy_services(self) -> Dict[str, Dict[str, Any]]:
        """Get only healthy services."""
        return {
            name: info for name, info in self._services.items()
            if info.get("status") == "healthy"
        }
    
    async def health_check_all(self) -> Dict[str, Dict[str, Any]]:
        """Perform health checks on all registered services."""
        results = {}
        
        for service_name, service_info in self._services.items():
            try:
                client = APIClient(service_info["url"], timeout=2.0)
                health_result = await client.health_check()
                
                service_info["last_health_check"] = datetime.now()
                service_info["status"] = health_result.get("status", "unknown")
                
                results[service_name] = {
                    "status": service_info["status"],
                    "url": service_info["url"],
                    "health_data": health_result
                }
                
                await client.close()
                
            except Exception as e:
                service_info["status"] = "unhealthy"
                service_info["last_health_check"] = datetime.now()
                
                results[service_name] = {
                    "status": "unhealthy",
                    "url": service_info["url"],
                    "error": str(e)
                }
                
                self._logger.warning(f"Health check failed for {service_name}: {e}")
        
        return results


# Global service registry instance
_service_registry = ServiceRegistry()


def get_service_registry() -> ServiceRegistry:
    """Get the global service registry instance."""
    return _service_registry


class ServiceConfig:
    """Enhanced configuration management for services."""
    
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
        
        # Auto-register service in registry
        self._register_service()
    
    def _register_service(self):
        """Register this service in the service registry."""
        registry = get_service_registry()
        registry.register_service(
            self.service_name,
            self.host,
            self.port,
            metadata={
                "version": "0.1.0",
                "started_at": datetime.now().isoformat()
            }
        )
    
    def get_service_url(self, service_name: str) -> str:
        """Get URL for another service, first trying registry, then fallback to port mapping."""
        try:
            registry = get_service_registry()
            return registry.get_service_url(service_name)
        except ValueError:
            # Fallback to port mapping
            port = self.port_mapping.get(service_name)
            if not port:
                raise ValueError(f"Unknown service: {service_name}")
            return f"http://{self.host}:{port}"
    
    def get_all_service_urls(self) -> Dict[str, str]:
        """Get URLs for all known services."""
        urls = {}
        registry = get_service_registry()
        
        for service_name in self.port_mapping.keys():
            try:
                urls[service_name] = self.get_service_url(service_name)
            except ValueError:
                continue
        
        return urls


class CircuitBreaker:
    """Circuit breaker pattern implementation for service resilience."""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0, 
                 expected_exception: type = Exception):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.logger = setup_logging("circuit-breaker")
    
    async def call(self, func: Callable, *args, **kwargs):
        """Execute function through circuit breaker."""
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
                self.logger.info("Circuit breaker transitioning to HALF_OPEN")
            else:
                raise ServiceError("Circuit breaker is OPEN", "CIRCUIT_BREAKER_OPEN")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        
        except self.expected_exception as e:
            self._on_failure()
            raise e
    
    def _should_attempt_reset(self) -> bool:
        """Check if circuit breaker should attempt to reset."""
        return (
            self.last_failure_time and
            time.time() - self.last_failure_time >= self.recovery_timeout
        )
    
    def _on_success(self):
        """Handle successful call."""
        self.failure_count = 0
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            self.logger.info("Circuit breaker reset to CLOSED")
    
    def _on_failure(self):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.logger.warning(f"Circuit breaker opened after {self.failure_count} failures")


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


def handle_service_error(e: Exception, logger: logging.Logger, context: str = "") -> Dict[str, Any]:
    """Handle service errors and create appropriate error responses."""
    if isinstance(e, ServiceError):
        logger.error(f"{context} - Service error: {e.message}")
        return create_error_response(e.error_code, e.message, e.details)
    
    elif isinstance(e, httpx.TimeoutException):
        logger.error(f"{context} - Request timeout: {e}")
        return create_error_response("TIMEOUT", "Request timed out", {"error": str(e)})
    
    elif isinstance(e, httpx.ConnectError):
        logger.error(f"{context} - Connection error: {e}")
        return create_error_response("CONNECTION_ERROR", "Failed to connect to service", {"error": str(e)})
    
    elif isinstance(e, httpx.HTTPStatusError):
        logger.error(f"{context} - HTTP error {e.response.status_code}: {e}")
        return create_error_response(
            "HTTP_ERROR", 
            f"HTTP {e.response.status_code} error",
            {"status_code": e.response.status_code, "error": str(e)}
        )
    
    else:
        logger.error(f"{context} - Unexpected error: {e}")
        return create_error_response("INTERNAL_ERROR", "An internal error occurred", {"error": str(e)})


async def with_error_handling(func: Callable, logger: logging.Logger, context: str = ""):
    """Execute function with standardized error handling."""
    try:
        return await func()
    except Exception as e:
        error_response = handle_service_error(e, logger, context)
        raise ServiceError(
            error_response["message"],
            error_response["error_code"],
            error_response["details"]
        )


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