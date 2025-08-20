#!/usr/bin/env python3
"""
Demonstration script showing RTB workflow console output.
This script shows how the detailed console logging works during RTB flow execution.
"""

import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# Import with correct directory name (hyphen, not underscore)
import importlib.util
spec = importlib.util.spec_from_file_location("ad_exchange_main", "server/ad-exchange/main.py")
ad_exchange_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ad_exchange_main)

from shared.models import UserProfile


async def demo_console_output():
    """Demonstrate RTB workflow with detailed console output."""
    print("🎬 RTB Workflow Console Output Demonstration")
    print("=" * 60)
    print()
    
    # Get the RTB orchestrator
    rtb_orchestrator = ad_exchange_main.rtb_orchestrator
    
    print("📋 This demonstration will show detailed console logs for each step:")
    print("   1. User visit simulation")
    print("   2. User profile fetching from DMP")
    print("   3. Ad request generation")
    print("   4. Bid request creation")
    print("   5. Parallel DSP auction")
    print("   6. Winning ad processing")
    print("   7. Data feedback loop")
    print()
    print("🚀 Starting RTB workflow execution...")
    print("=" * 60)
    
    try:
        # Custom user context for demonstration
        demo_context = {
            "user_id": "demo-user-console-001",
            "device_type": "desktop",
            "location": {
                "country": "US",
                "city": "San Francisco",
                "region": "CA"
            }
        }
        
        # Execute the complete RTB workflow
        # This will generate detailed console output for each step
        result = await rtb_orchestrator.execute_complete_rtb_workflow(demo_context)
        
        print("=" * 60)
        print("📊 RTB Workflow Execution Summary:")
        print(f"   Workflow ID: {result.get('workflow_id', 'unknown')}")
        print(f"   Status: {result.get('status', 'unknown')}")
        print(f"   Duration: {result.get('duration_ms', 0):.2f}ms")
        
        if result.get('status') == 'success':
            steps = result.get('steps', {})
            
            # User visit summary
            if 'user_visit' in steps:
                user_visit = steps['user_visit']
                print(f"   User ID: {user_visit.get('user_id', 'unknown')}")
                print(f"   Device: {user_visit.get('device_type', 'unknown')}")
                print(f"   Location: {user_visit.get('location', {}).get('city', 'unknown')}")
            
            # Auction summary
            if 'auction_result' in steps:
                auction = steps['auction_result']
                winning_bid = auction.get('winning_bid')
                if winning_bid:
                    print(f"   🏆 Winner: Campaign {winning_bid.get('campaign_id', 'unknown')}")
                    print(f"   💰 Price: ${auction.get('auction_price', 0):.4f}")
                    print(f"   📊 Total Bids: {len(auction.get('all_bids', []))}")
                else:
                    print("   ❌ No winning bid")
            
            # Display summary
            if 'display_result' in steps:
                display = steps['display_result']
                print(f"   📺 Impression Confirmed: {display.get('impression_confirmed', False)}")
                if display.get('impression_id'):
                    print(f"   🆔 Impression ID: {display.get('impression_id')}")
            
            # Feedback summary
            if 'feedback_result' in steps:
                feedback = steps['feedback_result']
                print("   🔄 Feedback Loop Results:")
                for service, result_data in feedback.items():
                    status = result_data.get('status', 'unknown')
                    emoji = "✅" if status == "success" else "❌"
                    print(f"      {emoji} {service.upper()}: {status}")
        
        else:
            print(f"   ❌ Error: {result.get('error', 'Unknown error')}")
        
        print("=" * 60)
        print("✨ Console output demonstration complete!")
        print()
        print("💡 Key Features Demonstrated:")
        print("   • Detailed step-by-step logging with timestamps")
        print("   • Structured data output for each workflow phase")
        print("   • Error handling with continued execution")
        print("   • Performance metrics and timing information")
        print("   • Service communication status tracking")
        
    except Exception as e:
        print("=" * 60)
        print(f"💥 Demo failed with error: {e}")
        print("Make sure all required services are available or properly mocked.")


async def demo_multiple_workflows():
    """Demonstrate multiple RTB workflows to show statistics tracking."""
    print("\n🔢 Multiple Workflow Statistics Demonstration")
    print("=" * 60)
    
    rtb_orchestrator = ad_exchange_main.rtb_orchestrator
    
    # Reset statistics
    rtb_orchestrator.workflow_stats = {
        "total_workflows": 0,
        "successful_workflows": 0,
        "failed_workflows": 0,
        "average_duration_ms": 0.0
    }
    
    print("Running 3 demo workflows to show statistics tracking...")
    print()
    
    for i in range(3):
        print(f"🚀 Executing workflow {i + 1}/3...")
        
        demo_context = {
            "user_id": f"demo-user-{i + 1:03d}",
            "device_type": ["desktop", "mobile", "tablet"][i % 3],
            "location": {
                "country": "US",
                "city": ["San Francisco", "New York", "Los Angeles"][i % 3],
                "region": ["CA", "NY", "CA"][i % 3]
            }
        }
        
        try:
            result = await rtb_orchestrator.execute_complete_rtb_workflow(demo_context)
            status = "✅ Success" if result.get('status') == 'success' else "❌ Failed"
            duration = result.get('duration_ms', 0)
            print(f"   {status} - Duration: {duration:.2f}ms")
        except Exception as e:
            print(f"   ❌ Failed - Error: {e}")
        
        print()
    
    # Show final statistics
    stats = rtb_orchestrator.workflow_stats
    print("📊 Final Statistics:")
    print(f"   Total Workflows: {stats['total_workflows']}")
    print(f"   Successful: {stats['successful_workflows']}")
    print(f"   Failed: {stats['failed_workflows']}")
    print(f"   Success Rate: {stats['successful_workflows'] / max(stats['total_workflows'], 1) * 100:.1f}%")
    print(f"   Average Duration: {stats['average_duration_ms']:.2f}ms")


if __name__ == "__main__":
    print("RTB Console Output Demonstration")
    print("This script shows the detailed console logging during RTB workflow execution.")
    print()
    
    try:
        # Run the main demonstration
        asyncio.run(demo_console_output())
        
        # Run the statistics demonstration
        asyncio.run(demo_multiple_workflows())
        
    except KeyboardInterrupt:
        print("\n⏹️  Demonstration interrupted by user")
    except Exception as e:
        print(f"\n💥 Demonstration failed with error: {e}")
        import traceback
        traceback.print_exc()