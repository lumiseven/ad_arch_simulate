#!/usr/bin/env python3
"""
Script to start all ad system services.
"""

import subprocess
import sys
import time
from pathlib import Path

# Service configurations
SERVICES = [
    {"name": "ad-management", "port": 8001, "path": "server/ad-management/main.py"},
    {"name": "dsp", "port": 8002, "path": "server/dsp/main.py"},
    {"name": "ssp", "port": 8003, "path": "server/ssp/main.py"},
    {"name": "ad-exchange", "port": 8004, "path": "server/ad-exchange/main.py"},
    {"name": "dmp", "port": 8005, "path": "server/dmp/main.py"},
]


def start_service(service):
    """Start a single service."""
    print(f"Starting {service['name']} on port {service['port']}...")
    
    # Change to project root directory
    project_root = Path(__file__).parent.parent
    
    try:
        process = subprocess.Popen([
            sys.executable, service['path']
        ], cwd=project_root)
        
        print(f"✓ {service['name']} started (PID: {process.pid})")
        return process
    except Exception as e:
        print(f"✗ Failed to start {service['name']}: {e}")
        return None


def main():
    """Start all services."""
    print("Starting Ad System Architecture Services...")
    print("=" * 50)
    
    processes = []
    
    for service in SERVICES:
        process = start_service(service)
        if process:
            processes.append(process)
        time.sleep(1)  # Small delay between service starts
    
    print("\n" + "=" * 50)
    print(f"Started {len(processes)} services successfully!")
    print("\nService URLs:")
    for service in SERVICES:
        print(f"  {service['name']}: http://127.0.0.1:{service['port']}")
    
    print("\nPress Ctrl+C to stop all services...")
    
    try:
        # Wait for all processes
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        print("\nStopping all services...")
        for process in processes:
            process.terminate()
        print("All services stopped.")


if __name__ == "__main__":
    main()