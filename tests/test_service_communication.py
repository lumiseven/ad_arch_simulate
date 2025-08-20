"""
Integration tests for service communication and error handling.
Tests the enhanced APIClient, service registry, and error handling mechanisms.
"""

import pytest
import asyncio
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

# Import the enhanced utilities
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.utils import (
    APIClient, ServiceRegistry, ServiceConfig, get_service_registry,
    ServiceError, ServiceUnavailableError, ServiceTimeoutError,
    handle_service_error, with_error_handling, CircuitBreaker,
    setup_logging
)
from shared.models import HealthCheck, ErrorResponse


class TestAPIClient:
    """Test cases for enhanced APIClient with retry logic."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.base_url = "http://localhost:8001"
        self.client = APIClient(self.base_url, timeout=1.0, max_retries=2)
    
    def teardown_method(self):
        """Clean up after tests."""
        asyncio.run(self.client.close())
    
    def test_client_initialization(self):
        """Test APIClient initialization."""
        assert self.client.base_url == self.base_url
        assert self.client.timeout == 1.0
        assert self.client.max_retries == 2
        assert self.client.service_name == "ad-management"
    
    def test_service_name_extraction(self):
        """Test service name extraction from URL."""
        test_cases = [
            ("http://localhost:8001", "ad-management"),
            ("http://localhost:8002", "dsp"),
            ("http://localhost:8003", "ssp"),
            ("http://localhost:8004", "ad-exchange"),
            ("http://localhost:8005", "dmp"),
            ("http://localhost:9999", "unknown")
        ]
        
        for url, expected_service in test_cases:
            client = APIClient(url)
            assert client.service_name == expected_service
            asyncio.run(client.close())
    
    @pytest.mark.asyncio
    async def test_successful_get_request(self):
        """Test successful GET request."""
        with patch.object(self.client.client, 'get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "success"}
            mock_get.return_value = mock_response
            
            result = await self.client.get("/test")
            
            assert result == {"status": "success"}
            mock_get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_successful_post_request(self):
        """Test successful POST request."""
        with patch.object(self.client.client, 'post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": "123"}
            mock_post.return_value = mock_response
            
            result = await self.client.post("/test", json_data={"name": "test"})
            
            assert result == {"id": "123"}
            mock_post.assert_called_once_with(
                f"{self.base_url}/test",
                json={"name": "test"}
            )
    
    @pytest.mark.asyncio
    async def test_timeout_error_with_retry(self):
        """Test timeout error handling with retry."""
        with patch.object(self.client.client, 'get') as mock_get:
            mock_get.side_effect = httpx.TimeoutException("Request timed out")
            
            with pytest.raises(ServiceTimeoutError) as exc_info:
                await self.client.get("/test")
            
            assert exc_info.value.service_name == "ad-management"
            assert exc_info.value.timeout == 1.0
            assert mock_get.call_count == 3  # Initial + 2 retries
    
    @pytest.mark.asyncio
    async def test_connection_error_with_retry(self):
        """Test connection error handling with retry."""
        with patch.object(self.client.client, 'get') as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection failed")
            
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await self.client.get("/test")
            
            assert exc_info.value.service_name == "ad-management"
            assert mock_get.call_count == 3  # Initial + 2 retries
    
    @pytest.mark.asyncio
    async def test_server_error_with_retry(self):
        """Test server error (5xx) handling with retry."""
        with patch.object(self.client.client, 'get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.request = MagicMock()
            mock_get.return_value = mock_response
            
            with pytest.raises(ServiceError) as exc_info:
                await self.client.get("/test")
            
            assert exc_info.value.error_code == "SERVER_ERROR"
            assert mock_get.call_count == 3  # Initial + 2 retries
    
    @pytest.mark.asyncio
    async def test_client_error_no_retry(self):
        """Test client error (4xx) handling without retry."""
        with patch.object(self.client.client, 'get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.json.return_value = {
                "error_code": "NOT_FOUND",
                "message": "Resource not found"
            }
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=mock_response
            )
            mock_get.return_value = mock_response
            
            with pytest.raises(ServiceError) as exc_info:
                await self.client.get("/test")
            
            assert exc_info.value.error_code == "NOT_FOUND"
            assert exc_info.value.message == "Resource not found"
            assert mock_get.call_count == 1  # No retry for client errors
    
    @pytest.mark.asyncio
    async def test_retry_with_eventual_success(self):
        """Test retry logic with eventual success."""
        with patch.object(self.client.client, 'get') as mock_get:
            # First call fails, second succeeds
            mock_response_fail = MagicMock()
            mock_response_fail.status_code = 500
            mock_response_fail.request = MagicMock()
            
            mock_response_success = MagicMock()
            mock_response_success.status_code = 200
            mock_response_success.json.return_value = {"status": "success"}
            
            mock_get.side_effect = [
                mock_response_fail,  # First attempt fails
                mock_response_success  # Second attempt succeeds
            ]
            
            result = await self.client.get("/test")
            
            assert result == {"status": "success"}
            assert mock_get.call_count == 2
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health check functionality."""
        with patch.object(self.client, 'get') as mock_get:
            mock_get.return_value = {
                "status": "healthy",
                "details": {"uptime": "5m"}
            }
            
            result = await self.client.health_check()
            
            assert result["status"] == "healthy"
            mock_get.assert_called_once_with("/health", retries=1)
    
    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Test health check failure handling."""
        with patch.object(self.client, 'get') as mock_get:
            mock_get.side_effect = ServiceUnavailableError("ad-management")
            
            result = await self.client.health_check()
            
            assert result["status"] == "unhealthy"
            assert "error" in result
            assert result["service"] == "ad-management"


class TestServiceRegistry:
    """Test cases for ServiceRegistry."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.registry = ServiceRegistry()
    
    def test_register_service(self):
        """Test service registration."""
        self.registry.register_service(
            "test-service", 
            "localhost", 
            8080,
            metadata={"version": "1.0.0"}
        )
        
        service = self.registry.get_service("test-service")
        assert service is not None
        assert service["name"] == "test-service"
        assert service["host"] == "localhost"
        assert service["port"] == 8080
        assert service["url"] == "http://localhost:8080"
        assert service["metadata"]["version"] == "1.0.0"
    
    def test_unregister_service(self):
        """Test service unregistration."""
        self.registry.register_service("test-service", "localhost", 8080)
        assert self.registry.get_service("test-service") is not None
        
        self.registry.unregister_service("test-service")
        assert self.registry.get_service("test-service") is None
    
    def test_get_service_url(self):
        """Test getting service URL."""
        self.registry.register_service("test-service", "localhost", 8080)
        
        url = self.registry.get_service_url("test-service")
        assert url == "http://localhost:8080"
    
    def test_get_service_url_not_found(self):
        """Test getting URL for non-existent service."""
        with pytest.raises(ValueError, match="Service unknown-service not found"):
            self.registry.get_service_url("unknown-service")
    
    def test_list_services(self):
        """Test listing all services."""
        self.registry.register_service("service1", "localhost", 8001)
        self.registry.register_service("service2", "localhost", 8002)
        
        services = self.registry.list_services()
        assert len(services) == 2
        assert "service1" in services
        assert "service2" in services
    
    def test_get_healthy_services(self):
        """Test getting only healthy services."""
        self.registry.register_service("healthy-service", "localhost", 8001)
        self.registry.register_service("unhealthy-service", "localhost", 8002)
        
        # Manually set status
        self.registry._services["healthy-service"]["status"] = "healthy"
        self.registry._services["unhealthy-service"]["status"] = "unhealthy"
        
        healthy_services = self.registry.get_healthy_services()
        assert len(healthy_services) == 1
        assert "healthy-service" in healthy_services
        assert "unhealthy-service" not in healthy_services
    
    @pytest.mark.asyncio
    async def test_health_check_all(self):
        """Test health checking all services."""
        self.registry.register_service("service1", "localhost", 8001)
        self.registry.register_service("service2", "localhost", 8002)
        
        with patch('shared.utils.APIClient') as mock_client_class:
            # Mock healthy service
            mock_client1 = AsyncMock()
            mock_client1.health_check.return_value = {"status": "healthy"}
            
            # Mock unhealthy service
            mock_client2 = AsyncMock()
            mock_client2.health_check.side_effect = Exception("Connection failed")
            
            mock_client_class.side_effect = [mock_client1, mock_client2]
            
            results = await self.registry.health_check_all()
            
            assert len(results) == 2
            assert results["service1"]["status"] == "healthy"
            assert results["service2"]["status"] == "unhealthy"
            assert "error" in results["service2"]


class TestServiceConfig:
    """Test cases for enhanced ServiceConfig."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Clear the global registry
        registry = get_service_registry()
        registry._services.clear()
    
    def test_service_config_initialization(self):
        """Test ServiceConfig initialization and auto-registration."""
        config = ServiceConfig("test-service")
        
        assert config.service_name == "test-service"
        assert config.host == "127.0.0.1"
        
        # Check auto-registration
        registry = get_service_registry()
        service = registry.get_service("test-service")
        assert service is not None
        assert service["name"] == "test-service"
    
    def test_get_service_url_from_registry(self):
        """Test getting service URL from registry."""
        config = ServiceConfig("test-service")
        
        # Register another service
        registry = get_service_registry()
        registry.register_service("other-service", "localhost", 9000)
        
        url = config.get_service_url("other-service")
        assert url == "http://localhost:9000"
    
    def test_get_service_url_fallback_to_port_mapping(self):
        """Test fallback to port mapping when service not in registry."""
        config = ServiceConfig("test-service")
        
        url = config.get_service_url("dsp")
        assert url == "http://127.0.0.1:8002"
    
    def test_get_all_service_urls(self):
        """Test getting all service URLs."""
        config = ServiceConfig("test-service")
        
        urls = config.get_all_service_urls()
        
        # Should include all services from port mapping
        expected_services = ["ad-management", "dsp", "ssp", "ad-exchange", "dmp"]
        for service in expected_services:
            assert service in urls


class TestErrorHandling:
    """Test cases for error handling utilities."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.logger = setup_logging("test-error-handling")
    
    def test_handle_service_error(self):
        """Test service error handling."""
        service_error = ServiceError("Test error", "TEST_ERROR", {"detail": "test"})
        
        result = handle_service_error(service_error, self.logger, "test context")
        
        assert result["error_code"] == "TEST_ERROR"
        assert result["message"] == "Test error"
        assert result["details"]["detail"] == "test"
    
    def test_handle_timeout_error(self):
        """Test timeout error handling."""
        timeout_error = httpx.TimeoutException("Request timed out")
        
        result = handle_service_error(timeout_error, self.logger)
        
        assert result["error_code"] == "TIMEOUT"
        assert result["message"] == "Request timed out"
    
    def test_handle_connection_error(self):
        """Test connection error handling."""
        connection_error = httpx.ConnectError("Connection failed")
        
        result = handle_service_error(connection_error, self.logger)
        
        assert result["error_code"] == "CONNECTION_ERROR"
        assert result["message"] == "Failed to connect to service"
    
    def test_handle_http_status_error(self):
        """Test HTTP status error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        http_error = httpx.HTTPStatusError("404 Not Found", request=MagicMock(), response=mock_response)
        
        result = handle_service_error(http_error, self.logger)
        
        assert result["error_code"] == "HTTP_ERROR"
        assert result["message"] == "HTTP 404 error"
        assert result["details"]["status_code"] == 404
    
    def test_handle_generic_error(self):
        """Test generic error handling."""
        generic_error = ValueError("Invalid value")
        
        result = handle_service_error(generic_error, self.logger)
        
        assert result["error_code"] == "INTERNAL_ERROR"
        assert result["message"] == "An internal error occurred"
    
    @pytest.mark.asyncio
    async def test_with_error_handling_success(self):
        """Test with_error_handling for successful function."""
        async def success_func():
            return {"result": "success"}
        
        result = await with_error_handling(success_func, self.logger)
        assert result == {"result": "success"}
    
    @pytest.mark.asyncio
    async def test_with_error_handling_failure(self):
        """Test with_error_handling for failing function."""
        async def failing_func():
            raise httpx.TimeoutException("Request timed out")
        
        with pytest.raises(ServiceError) as exc_info:
            await with_error_handling(failing_func, self.logger, "test context")
        
        assert exc_info.value.error_code == "TIMEOUT"


class TestCircuitBreaker:
    """Test cases for CircuitBreaker."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.circuit_breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=1.0)
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_closed_state(self):
        """Test circuit breaker in CLOSED state."""
        async def success_func():
            return "success"
        
        result = await self.circuit_breaker.call(success_func)
        assert result == "success"
        assert self.circuit_breaker.state == "CLOSED"
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self):
        """Test circuit breaker opens after threshold failures."""
        async def failing_func():
            raise Exception("Test failure")
        
        # First failure
        with pytest.raises(Exception):
            await self.circuit_breaker.call(failing_func)
        assert self.circuit_breaker.state == "CLOSED"
        
        # Second failure - should open circuit
        with pytest.raises(Exception):
            await self.circuit_breaker.call(failing_func)
        assert self.circuit_breaker.state == "OPEN"
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_open_state(self):
        """Test circuit breaker in OPEN state."""
        # Force circuit to OPEN state
        self.circuit_breaker.state = "OPEN"
        self.circuit_breaker.last_failure_time = time.time() - 0.5  # Recent failure
        
        async def any_func():
            return "should not execute"
        
        with pytest.raises(ServiceError, match="Circuit breaker is OPEN"):
            await self.circuit_breaker.call(any_func)
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_recovery(self):
        """Test circuit breaker recovery through HALF_OPEN state."""
        # Force circuit to OPEN state with old failure time
        self.circuit_breaker.state = "OPEN"
        self.circuit_breaker.last_failure_time = time.time() - 2.0  # Old failure
        
        async def success_func():
            return "recovered"
        
        result = await self.circuit_breaker.call(success_func)
        assert result == "recovered"
        assert self.circuit_breaker.state == "CLOSED"
        assert self.circuit_breaker.failure_count == 0


class TestServiceCommunicationIntegration:
    """Integration tests for service communication."""
    
    def setup_method(self):
        """Set up integration test fixtures."""
        self.registry = ServiceRegistry()
        self.config = ServiceConfig("test-service")
    
    @pytest.mark.asyncio
    async def test_full_service_communication_flow(self):
        """Test complete service communication flow."""
        # Register services
        self.registry.register_service("service-a", "localhost", 8001)
        self.registry.register_service("service-b", "localhost", 8002)
        
        # Create API client
        client = APIClient("http://localhost:8001", max_retries=1)
        
        # Mock successful communication
        with patch.object(client.client, 'get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "healthy",
                "details": {"service": "service-a"}
            }
            mock_get.return_value = mock_response
            
            # Test health check
            health_result = await client.health_check()
            assert health_result["status"] == "healthy"
            
            # Test regular API call
            api_result = await client.get("/api/test")
            assert api_result["status"] == "healthy"
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_service_discovery_and_communication(self):
        """Test service discovery and communication integration."""
        # Register target service
        self.registry.register_service("target-service", "localhost", 8080)
        
        # Get service URL through config
        url = self.config.get_service_url("target-service")
        assert url == "http://localhost:8080"
        
        # Create client and test communication
        client = APIClient(url)
        
        with patch.object(client.client, 'post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": "created"}
            mock_post.return_value = mock_response
            
            result = await client.post("/create", json_data={"name": "test"})
            assert result["id"] == "created"
        
        await client.close()
    
    @pytest.mark.asyncio
    async def test_error_propagation_across_services(self):
        """Test error propagation across service boundaries."""
        client = APIClient("http://localhost:8001")
        
        # Test service unavailable error
        with patch.object(client.client, 'get') as mock_get:
            mock_get.side_effect = httpx.ConnectError("Service unavailable")
            
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await client.get("/test")
            
            assert exc_info.value.service_name == "ad-management"
            assert "Service ad-management is unavailable" in str(exc_info.value)
        
        await client.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])