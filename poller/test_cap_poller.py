#!/usr/bin/env python3
"""
Test script to verify the CAP poller is working with database integration
"""

import sys
import os
import logging
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cap_poller import CAPPoller
from app import app, db, CAPAlert, Boundary, SystemLog

def test_database_connection():
    """Test database connectivity"""
    print("?? Testing Database Connection...")
    
    try:
        with app.app_context():
            # Test basic connection
            result = db.session.execute(db.text('SELECT 1 as test')).fetchone()
            print(f"? Database connection: OK (test result: {result[0]})")
            
            # Check table existence
            tables = db.session.execute(db.text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema='public' 
                AND table_name IN ('cap_alerts', 'boundaries', 'system_log')
            """)).fetchall()
            
            table_names = [t[0] for t in tables]
            print(f"?? Found tables: {table_names}")
            
            # Count existing data
            alert_count = CAPAlert.query.count()
            boundary_count = Boundary.query.count()
            log_count = SystemLog.query.count()
            
            print(f"?? Current data:")
            print(f"  - CAP Alerts: {alert_count}")
            print(f"  - Boundaries: {boundary_count}")
            print(f"  - System Logs: {log_count}")
            
            return True
            
    except Exception as e:
        print(f"? Database connection failed: {e}")
        return False

def test_cap_poller_standalone():
    """Test the CAP poller in standalone mode"""
    print("\n?? Testing CAP Poller Standalone...")
    
    try:
        with app.app_context():
            # Create poller instance
            poller = CAPPoller()
            
            print("?? Running poll cycle...")
            stats = poller.poll_and_process()
            
            print(f"?? Poll Results:")
            print(f"  - Status: {stats['status']}")
            print(f"  - Zone: {stats.get('zone', 'Unknown')}")
            print(f"  - Alerts Fetched: {stats['alerts_fetched']}")
            print(f"  - New Alerts: {stats['alerts_new']}")
            print(f"  - Updated Alerts: {stats['alerts_updated']}")
            print(f"  - Execution Time: {stats['execution_time_ms']}ms")
            
            if stats['status'] == 'ERROR':
                print(f"? Error: {stats.get('error_message', 'Unknown error')}")
                return False
            
            # Check database for new alerts
            with app.app_context():
                recent_alerts = CAPAlert.query.filter(
                    CAPAlert.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)
                ).all()
                
                print(f"\n?? Alerts in database from today: {len(recent_alerts)}")
                
                if recent_alerts:
                    for alert in recent_alerts[-3:]:  # Show last 3
                        print(f"  - {alert.event}: {alert.severity} ({alert.identifier[:20]}...)")
                
                # Check system logs
                recent_logs = SystemLog.query.filter(
                    SystemLog.module == 'cap_poller'
                ).order_by(SystemLog.timestamp.desc()).limit(3).all()
                
                print(f"\n?? Recent CAP poller logs: {len(recent_logs)}")
                for log in recent_logs:
                    print(f"  - {log.timestamp.strftime('%H:%M:%S')} [{log.level}]: {log.message}")
            
            poller.close()
            return True
            
    except Exception as e:
        print(f"? CAP Poller test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_flask_integration():
    """Test the Flask admin trigger integration"""
    print("\n?? Testing Flask Integration...")
    
    try:
        with app.test_client() as client:
            # Test the system status endpoint
            response = client.get('/api/system_status')
            if response.status_code == 200:
                data = response.get_json()
                print(f"? System Status API: OK")
                print(f"  - Active Alerts: {data.get('active_alerts_count', 'Unknown')}")
                print(f"  - Database Status: {data.get('database_status', 'Unknown')}")
            else:
                print(f"? System Status API failed: {response.status_code}")
            
            # Test the manual trigger endpoint
            response = client.post('/admin/trigger_poll')
            if response.status_code == 200:
                data = response.get_json()
                print(f"? Manual Trigger API: OK")
                print(f"  - Message: {data.get('message', 'No message')}")
            else:
                print(f"? Manual Trigger API failed: {response.status_code}")
                
        return True
        
    except Exception as e:
        print(f"? Flask integration test failed: {e}")
        return False

def main():
    """Run comprehensive CAP poller tests"""
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("?? NOAA CAP Poller Integration Test")
    print(f"? Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    tests = [
        ("Database Connection", test_database_connection),
        ("CAP Poller Standalone", test_cap_poller_standalone),
        ("Flask Integration", test_flask_integration)
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        print(f"\n?? Running: {test_name}")
        print("-" * 40)
        
        try:
            result = test_func()
            results[test_name] = result
            status = "? PASSED" if result else "? FAILED"
            print(f"\n{status}: {test_name}")
            
        except Exception as e:
            print(f"\n? EXCEPTION in {test_name}: {e}")
            results[test_name] = False
    
    # Summary
    print("\n" + "=" * 60)
    print("?? TEST SUMMARY")
    print("=" * 60)
    
    for test_name, result in results.items():
        status = "? PASSED" if result else "? FAILED"
        print(f"{status}: {test_name}")
    
    total_passed = sum(results.values())
    total_tests = len(results)
    
    print(f"\n?? Overall: {total_passed}/{total_tests} tests passed")
    
    if total_passed == total_tests:
        print("?? All tests passed! CAP poller is working correctly.")
        print("\n?? Next steps:")
        print("- Set up automated polling (cron job or systemd service)")
        print("- Test with real weather alerts when they occur")
        print("- Monitor system logs for ongoing operation")
    else:
        print("??  Some tests failed. Check the errors above.")
        print("\n?? Troubleshooting:")
        print("- Verify database connection and permissions")
        print("- Check network connectivity to api.weather.gov")
        print("- Ensure Flask app is properly configured")

if __name__ == '__main__':
    main()