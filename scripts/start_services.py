#!/usr/bin/env python3
"""
Enhanced script to start all services for the ad system architecture.
Includes service registration, health monitoring, and graceful shutdown.
"""

import subprocess
import time
import sys
import os
import asyncio
import signal
from pathlib import Path
from typing import List, Tuple, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.utils import get_service_registry, setup_logging
from shared.monitoring import get_service_monitor


class ServiceManager:
    """Manages starting, stopping, and monitoring services."""
    
    def __init__(self):
        self.logger = setup_logging("service-manager")
        self.processes: List[Tuple[str, subprocess.Popen]] = []
        self.registry = get_service_registry()
        self.monitor = get_service_monitor()
        self.shutdown_requested = False
    
    def start_service(self, service_name: str, port: int) -> Optional[subprocess.Popen]:
        """Start a service in a separate process."""
        service_path = Path(__file__).parent.parent / "server" / service_name / "main.py"
        
        if not service_path.exists():
            self.logger.error(f"Service file not found: {service_path}")
            return None
        
        self.logger.info(f"Starting {service_name} on port {port}...")
        
        # Start the service
        try:
            process = subprocess.Popen([
                sys.executable, str(service_path)
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Register service in registry
            self.registry.register_service(
                service_name,
                "127.0.0.1",
                port,
                metadata={
                    "pid": process.pid,
                    "started_at": time.time()
                }
            )
            
            return process
            
        except Exception as e:
            self.logger.error(f"Failed to start {service_name}: {e}")
            return None
    
    async def wait_for_service_ready(self, service_name: str, max_wait: int = 30) -> bool:
        """Wait for a service to be ready and healthy."""
        self.logger.info(f"Waiting for {service_name} to be ready...")
        
        for attempt in range(max_wait):
            try:
                service_info = self.registry.get_service(service_name)
                if service_info:
                    health_info = await self.monitor.check_service_health(
                        service_name, 
                        service_info["url"]
                    )
                    
                    if health_info.status.value in ["healthy", "degraded"]:
                        self.logger.info(f"{service_name} is ready!")
                        return True
                
            except Exception as e:
                self.logger.debug(f"Service {service_name} not ready yet: {e}")
            
            await asyncio.sleep(1)
        
        self.logger.warning(f"{service_name} did not become ready within {max_wait} seconds")
        return False
    
    async def start_all_services(self):
        """Start all services in the correct order."""
        # Define services with their dependencies
        services = [
            ("dmp", 8005, []),  # No dependencies
            ("ad-management", 8001, []),  # No dependencies
            ("dsp", 8002, ["dmp", "ad-management"]),  # Depends on DMP and Ad Management
            ("ssp", 8003, []),  # No dependencies (will connect to Ad Exchange)
            ("ad-exchange", 8004, ["dsp", "ssp", "dmp"]),  # Depends on DSP, SSP, DMP
        ]
        
        for service_name, port, dependencies in services:
            # Wait for dependencies to be ready
            for dep in dependencies:
                if not await self.wait_for_service_ready(dep, max_wait=10):
                    self.logger.error(f"Dependency {dep} not ready, but continuing with {service_name}")
            
            # Start the service
            process = self.start_service(service_name, port)
            if process:
                self.processes.append((service_name, process))
                
                # Wait for service to be ready before starting next one
                await self.wait_for_service_ready(service_name)
            else:
                self.logger.error(f"Failed to start {service_name}")
                return False
        
        return True
    
    async def health_check_all(self):
        """Perform health check on all services."""
        self.logger.info("Performing health check on all services...")
        
        health_results = await self.monitor.check_all_services()
        
        for service_name, health_info in health_results.items():
            status_emoji = {
                "healthy": "✅",
                "degraded": "⚠️",
                "unhealthy": "❌",
                "unknown": "❓"
            }.get(health_info.status.value, "❓")
            
            self.logger.info(
                f"{status_emoji} {service_name}: {health_info.status.value} "
                f"({health_info.response_time_ms:.2f}ms)"
            )
            
            if health_info.error:
                self.logger.warning(f"   Error: {health_info.error}")
    
    def stop_all_services(self):
        """Stop all running services."""
        self.logger.info("Stopping all services...")
        
        for service_name, process in reversed(self.processes):  # Stop in reverse order
            self.logger.info(f"Stopping {service_name}...")
            
            try:
                # Try graceful shutdown first
                process.terminate()
                
                # Wait up to 5 seconds for graceful shutdown
                try:
                    process.wait(timeout=5)
                    self.logger.info(f"{service_name} stopped gracefully")
                except subprocess.TimeoutExpired:
                    # Force kill if graceful shutdown fails
                    self.logger.warning(f"Force killing {service_name}")
                    process.kill()
                    process.wait()
                
                # Unregister from registry
                self.registry.unregister_service(service_name)
                
            except Exception as e:
                self.logger.error(f"Error stopping {service_name}: {e}")
        
        self.processes.clear()
        self.logger.info("All services stopped")
    
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, initiating shutdown...")
            self.shutdown_requested = True
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def run_monitoring_loop(self):
        """Run the main monitoring loop."""
        self.logger.info("Starting monitoring loop...")
        
        # Start continuous monitoring
        await self.monitor.start_monitoring()
        
        try:
            while not self.shutdown_requested:
                # Perform periodic health checks
                await self.health_check_all()
                
                # Check for alerts
                alerts = self.monitor.check_alerts()
                for alert in alerts:
                    self.logger.warning(
                        f"🚨 ALERT [{alert['severity']}] {alert['service']}: {alert['message']}"
                    )
                
                # Check if any processes have died
                for service_name, process in self.processes[:]:  # Copy list to avoid modification during iteration
                    if process.poll() is not None:  # Process has terminated
                        self.logger.error(f"Service {service_name} has died unexpectedly!")
                        self.processes.remove((service_name, process))
                        self.registry.unregister_service(service_name)
                
                # Wait before next check
                await asyncio.sleep(30)  # Check every 30 seconds
                
        except Exception as e:
            self.logger.error(f"Error in monitoring loop: {e}")
        finally:
            await self.monitor.stop_monitoring()
    
    async def run(self):
        """Main run method."""
        self.setup_signal_handlers()
        
        try:
            # Start all services
            self.logger.info("🚀 Starting Ad System Services...")
            
            if not await self.start_all_services():
                self.logger.error("Failed to start all services")
                return 1
            
            self.logger.info(f"✅ All {len(self.processes)} services started successfully!")
            
            # Initial health check
            await asyncio.sleep(2)  # Give services time to fully start
            await self.health_check_all()
            
            # Show system overview
            overview = self.monitor.get_system_health_overview()
            self.logger.info(f"📊 System Status: {overview['system_status']}")
            self.logger.info(f"📈 Services: {overview['healthy_services']} healthy, "
                           f"{overview['degraded_services']} degraded, "
                           f"{overview['unhealthy_services']} unhealthy")
            
            self.logger.info("🔍 Monitoring services... Press Ctrl+C to stop.")
            
            # Run monitoring loop
            await self.run_monitoring_loop()
            
        except KeyboardInterrupt:
            self.logger.info("Shutdown requested by user")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            return 1
        finally:
            self.stop_all_services()
        
        return 0


async def main():
    """Main entry point."""
    manager = ServiceManager()
    return await manager.run()


def sync_main():
    """Synchronous wrapper for main."""
    try:
        return asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown requested")
        return 0


if __name__ == "__main__":
    sys.exit(sync_main())