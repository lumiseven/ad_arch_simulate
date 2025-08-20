#!/usr/bin/env python3
"""
Simple test script to verify RTB demo endpoints work correctly.
"""

import asyncio
import httpx
import json
from datetime import datetime


async def test_demo_endpoints():
    """Test the RTB demo endpoints."""
    base_url = "http://127.0.0.1:8004"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("🚀 Testing RTB Demo Endpoints")
        print("=" * 50)
        
        # Test 1: Health check
        print("\n1. Testing health check endpoint...")
        try:
            response = await client.get(f"{base_url}/health")
            if response.status_code == 200:
                print("✅ Health check passed")
                health_data = response.json()
                print(f"   Service: {health_data['details']['service']}")
                print(f"   Status: {health_data['status']}")
            else:
                print(f"❌ Health check failed: {response.status_code}")
        except Exception as e:
            print(f"❌ Health check error: {e}")
        
        # Test 2: Simple RTB demo flow
        print("\n2. Testing simple RTB demo flow...")
        try:
            response = await client.post(f"{base_url}/demo/rtb-flow-simple")
            if response.status_code == 200:
                print("✅ Simple RTB demo passed")
                demo_data = response.json()
                print(f"   Status: {demo_data['status']}")
                print(f"   Duration: {demo_data.get('duration_ms', 0):.2f}ms")
                print(f"   Winning Campaign: {demo_data.get('winning_campaign', 'None')}")
                print(f"   Final Price: ${demo_data.get('final_price', 0):.4f}")
                print(f"   Impression Confirmed: {demo_data.get('impression_confirmed', False)}")
            else:
                print(f"❌ Simple RTB demo failed: {response.status_code}")
                print(f"   Response: {response.text}")
        except Exception as e:
            print(f"❌ Simple RTB demo error: {e}")
        
        # Test 3: Full RTB demo flow
        print("\n3. Testing full RTB demo flow...")
        try:
            custom_context = {
                "user_id": "test-user-123",
                "device_type": "desktop",
                "location": {"country": "US", "city": "San Francisco", "region": "CA"}
            }
            
            response = await client.post(f"{base_url}/demo/rtb-flow", json=custom_context)
            if response.status_code == 200:
                print("✅ Full RTB demo passed")
                demo_data = response.json()
                workflow_result = demo_data.get('workflow_result', {})
                print(f"   Status: {workflow_result.get('status', 'unknown')}")
                print(f"   Duration: {workflow_result.get('duration_ms', 0):.2f}ms")
                
                steps = workflow_result.get('steps', {})
                if 'user_visit' in steps:
                    user_visit = steps['user_visit']
                    print(f"   User ID: {user_visit.get('user_id', 'unknown')}")
                    print(f"   Device: {user_visit.get('device_type', 'unknown')}")
                
                if 'auction_result' in steps:
                    auction = steps['auction_result']
                    winning_bid = auction.get('winning_bid')
                    if winning_bid:
                        print(f"   Winning Campaign: {winning_bid.get('campaign_id', 'unknown')}")
                        print(f"   Auction Price: ${auction.get('auction_price', 0):.4f}")
                    else:
                        print("   No winning bid")
            else:
                print(f"❌ Full RTB demo failed: {response.status_code}")
                print(f"   Response: {response.text}")
        except Exception as e:
            print(f"❌ Full RTB demo error: {e}")
        
        # Test 4: Workflow statistics
        print("\n4. Testing workflow statistics...")
        try:
            response = await client.get(f"{base_url}/demo/workflow-stats")
            if response.status_code == 200:
                print("✅ Workflow stats retrieved")
                stats_data = response.json()
                workflow_stats = stats_data.get('workflow_statistics', {})
                print(f"   Total Workflows: {workflow_stats.get('total_workflows', 0)}")
                print(f"   Successful: {workflow_stats.get('successful_workflows', 0)}")
                print(f"   Failed: {workflow_stats.get('failed_workflows', 0)}")
                print(f"   Average Duration: {workflow_stats.get('average_duration_ms', 0):.2f}ms")
            else:
                print(f"❌ Workflow stats failed: {response.status_code}")
        except Exception as e:
            print(f"❌ Workflow stats error: {e}")
        
        # Test 5: Reset statistics
        print("\n5. Testing statistics reset...")
        try:
            response = await client.post(f"{base_url}/demo/reset-stats")
            if response.status_code == 200:
                print("✅ Statistics reset successful")
                reset_data = response.json()
                print(f"   Status: {reset_data.get('status', 'unknown')}")
                print(f"   Message: {reset_data.get('message', 'No message')}")
            else:
                print(f"❌ Statistics reset failed: {response.status_code}")
        except Exception as e:
            print(f"❌ Statistics reset error: {e}")
        
        print("\n" + "=" * 50)
        print("🎉 RTB Demo Endpoint Testing Complete!")


if __name__ == "__main__":
    print("RTB Demo Endpoint Tester")
    print("Make sure the Ad Exchange service is running on port 8004")
    print("You can start it with: uv run python server/ad-exchange/main.py")
    print()
    
    try:
        asyncio.run(test_demo_endpoints())
    except KeyboardInterrupt:
        print("\n⏹️  Testing interrupted by user")
    except Exception as e:
        print(f"\n💥 Testing failed with error: {e}")