"""
Service monitoring and health check utilities.
Provides centralized monitoring capabilities for all services.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from .utils import APIClient, ServiceConfig, get_service_registry, setup_logging
from .models import HealthCheck


class ServiceStatus(str, Enum):
    """Service status enumeration."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class ServiceHealthInfo:
    """Service health information."""
    service_name: str
    status: ServiceStatus
    url: str
    response_time_ms: float
    last_check: datetime
    details: Dict[str, Any]
    error: Optional[str] = None


class ServiceMonitor:
    """Service monitoring and health checking."""
    
    def __init__(self, check_interval: float = 30.0):
        self.check_interval = check_interval
        self.logger = setup_logging("service-monitor")
        self.health_history: Dict[str, List[ServiceHealthInfo]] = {}
        self.alert_thresholds = {
            "response_time_ms": 5000,  # 5 seconds
            "failure_rate": 0.5,  # 50% failure rate
            "consecutive_failures": 3
        }
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
    
    async def check_service_health(self, service_name: str, service_url: str) -> ServiceHealthInfo:
        """Check health of a single service."""
        start_time = datetime.now()
        
        try:
            client = APIClient(service_url, timeout=5.0, max_retries=1)
            
            # Measure response time
            health_data = await client.health_check()
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            # Parse health status
            status_str = health_data.get("status", "unknown").lower()
            status = ServiceStatus(status_str) if status_str in ServiceStatus.__members__.values() else ServiceStatus.UNKNOWN
            
            health_info = ServiceHealthInfo(
                service_name=service_name,
                status=status,
                url=service_url,
                response_time_ms=response_time,
                last_check=datetime.now(),
                details=health_data.get("details", {}),
                error=None
            )
            
            await client.close()
            
            self.logger.debug(f"Health check for {service_name}: {status.value} ({response_time:.2f}ms)")
            return health_info
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            health_info = ServiceHealthInfo(
                service_name=service_name,
                status=ServiceStatus.UNHEALTHY,
                url=service_url,
                response_time_ms=response_time,
                last_check=datetime.now(),
                details={},
                error=str(e)
            )
            
            self.logger.warning(f"Health check failed for {service_name}: {e}")
            return health_info
    
    async def check_all_services(self) -> Dict[str, ServiceHealthInfo]:
        """Check health of all registered services."""
        registry = get_service_registry()
        services = registry.list_services()
        
        health_results = {}
        
        # Check all services concurrently
        tasks = []
        for service_name, service_info in services.items():
            task = asyncio.create_task(
                self.check_service_health(service_name, service_info["url"])
            )
            tasks.append((service_name, task))
        
        # Wait for all health checks to complete
        for service_name, task in tasks:
            try:
                health_info = await task
                health_results[service_name] = health_info
                
                # Store in history
                if service_name not in self.health_history:
                    self.health_history[service_name] = []
                
                self.health_history[service_name].append(health_info)
                
                # Keep only last 100 entries
                if len(self.health_history[service_name]) > 100:
                    self.health_history[service_name] = self.health_history[service_name][-100:]
                
            except Exception as e:
                self.logger.error(f"Failed to check health for {service_name}: {e}")
        
        return health_results
    
    def get_service_health_summary(self, service_name: str, hours: int = 24) -> Dict[str, Any]:
        """Get health summary for a service over the specified time period."""
        if service_name not in self.health_history:
            return {"error": "No health data available"}
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_checks = [
            check for check in self.health_history[service_name]
            if check.last_check >= cutoff_time
        ]
        
        if not recent_checks:
            return {"error": "No recent health data available"}
        
        # Calculate metrics
        total_checks = len(recent_checks)
        healthy_checks = len([c for c in recent_checks if c.status == ServiceStatus.HEALTHY])
        unhealthy_checks = len([c for c in recent_checks if c.status == ServiceStatus.UNHEALTHY])
        degraded_checks = len([c for c in recent_checks if c.status == ServiceStatus.DEGRADED])
        
        response_times = [c.response_time_ms for c in recent_checks if c.error is None]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        max_response_time = max(response_times) if response_times else 0
        
        # Calculate uptime percentage
        uptime_percentage = (healthy_checks + degraded_checks) / total_checks * 100
        
        # Get current status
        current_status = recent_checks[-1].status if recent_checks else ServiceStatus.UNKNOWN
        
        return {
            "service_name": service_name,
            "current_status": current_status.value,
            "period_hours": hours,
            "total_checks": total_checks,
            "uptime_percentage": round(uptime_percentage, 2),
            "status_distribution": {
                "healthy": healthy_checks,
                "unhealthy": unhealthy_checks,
                "degraded": degraded_checks
            },
            "response_time_ms": {
                "average": round(avg_response_time, 2),
                "maximum": round(max_response_time, 2)
            },
            "last_check": recent_checks[-1].last_check.isoformat() if recent_checks else None
        }
    
    def get_system_health_overview(self) -> Dict[str, Any]:
        """Get overall system health overview."""
        registry = get_service_registry()
        services = registry.list_services()
        
        if not services:
            return {"error": "No services registered"}
        
        # Get latest health info for each service
        service_statuses = {}
        total_services = len(services)
        healthy_services = 0
        degraded_services = 0
        unhealthy_services = 0
        
        for service_name in services.keys():
            if service_name in self.health_history and self.health_history[service_name]:
                latest_check = self.health_history[service_name][-1]
                service_statuses[service_name] = {
                    "status": latest_check.status.value,
                    "response_time_ms": latest_check.response_time_ms,
                    "last_check": latest_check.last_check.isoformat(),
                    "error": latest_check.error
                }
                
                if latest_check.status == ServiceStatus.HEALTHY:
                    healthy_services += 1
                elif latest_check.status == ServiceStatus.DEGRADED:
                    degraded_services += 1
                else:
                    unhealthy_services += 1
            else:
                service_statuses[service_name] = {
                    "status": "unknown",
                    "error": "No health data available"
                }
                unhealthy_services += 1
        
        # Determine overall system status
        if unhealthy_services == 0:
            if degraded_services == 0:
                system_status = "healthy"
            else:
                system_status = "degraded"
        else:
            system_status = "unhealthy"
        
        return {
            "system_status": system_status,
            "total_services": total_services,
            "healthy_services": healthy_services,
            "degraded_services": degraded_services,
            "unhealthy_services": unhealthy_services,
            "service_details": service_statuses,
            "last_updated": datetime.now().isoformat()
        }
    
    def check_alerts(self) -> List[Dict[str, Any]]:
        """Check for service alerts based on thresholds."""
        alerts = []
        
        for service_name, checks in self.health_history.items():
            if not checks:
                continue
            
            recent_checks = checks[-10:]  # Last 10 checks
            
            # Check response time alert
            avg_response_time = sum(c.response_time_ms for c in recent_checks if c.error is None) / len(recent_checks)
            if avg_response_time > self.alert_thresholds["response_time_ms"]:
                alerts.append({
                    "type": "high_response_time",
                    "service": service_name,
                    "message": f"Average response time {avg_response_time:.2f}ms exceeds threshold {self.alert_thresholds['response_time_ms']}ms",
                    "severity": "warning",
                    "timestamp": datetime.now().isoformat()
                })
            
            # Check failure rate alert
            failed_checks = len([c for c in recent_checks if c.status == ServiceStatus.UNHEALTHY])
            failure_rate = failed_checks / len(recent_checks)
            if failure_rate > self.alert_thresholds["failure_rate"]:
                alerts.append({
                    "type": "high_failure_rate",
                    "service": service_name,
                    "message": f"Failure rate {failure_rate:.2%} exceeds threshold {self.alert_thresholds['failure_rate']:.2%}",
                    "severity": "critical",
                    "timestamp": datetime.now().isoformat()
                })
            
            # Check consecutive failures
            consecutive_failures = 0
            for check in reversed(recent_checks):
                if check.status == ServiceStatus.UNHEALTHY:
                    consecutive_failures += 1
                else:
                    break
            
            if consecutive_failures >= self.alert_thresholds["consecutive_failures"]:
                alerts.append({
                    "type": "consecutive_failures",
                    "service": service_name,
                    "message": f"{consecutive_failures} consecutive failures detected",
                    "severity": "critical",
                    "timestamp": datetime.now().isoformat()
                })
        
        return alerts
    
    async def start_monitoring(self):
        """Start continuous monitoring."""
        if self._monitoring:
            self.logger.warning("Monitoring is already running")
            return
        
        self._monitoring = True
        self.logger.info(f"Starting service monitoring with {self.check_interval}s interval")
        
        self._monitor_task = asyncio.create_task(self._monitoring_loop())
    
    async def stop_monitoring(self):
        """Stop continuous monitoring."""
        if not self._monitoring:
            return
        
        self._monitoring = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("Service monitoring stopped")
    
    async def _monitoring_loop(self):
        """Main monitoring loop."""
        while self._monitoring:
            try:
                health_results = await self.check_all_services()
                
                # Log summary
                healthy_count = len([h for h in health_results.values() if h.status == ServiceStatus.HEALTHY])
                total_count = len(health_results)
                
                self.logger.info(f"Health check completed: {healthy_count}/{total_count} services healthy")
                
                # Check for alerts
                alerts = self.check_alerts()
                for alert in alerts:
                    self.logger.warning(f"ALERT [{alert['severity']}] {alert['service']}: {alert['message']}")
                
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
            
            # Wait for next check
            await asyncio.sleep(self.check_interval)


# Global monitor instance
_service_monitor = ServiceMonitor()


def get_service_monitor() -> ServiceMonitor:
    """Get the global service monitor instance."""
    return _service_monitor