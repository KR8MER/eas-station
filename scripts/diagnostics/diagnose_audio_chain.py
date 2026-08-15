#!/usr/bin/env python3
"""
Diagnostic script to check the complete audio chain for SDR sources.

This script checks:
1. Radio receivers in database (LP1, LP2, SP1)
2. Audio source configs for each receiver
3. Redis connectivity and published IQ samples
4. Audio service metrics
5. EAS monitor status

Usage:
    python diagnose_audio_chain.py
"""

import os
import sys
import json
import time
from dotenv import load_dotenv

# Load environment
config_path = os.environ.get('CONFIG_PATH', '.env')
if os.path.exists(config_path):
    load_dotenv(config_path, override=True)
    print(f"✅ Loaded environment from: {config_path}")
else:
    load_dotenv(override=True)
    print(f"⚠️  Using default .env")

# Initialize Flask app for database access
from flask import Flask
from app_core.extensions import db
from app_core.models import RadioReceiver, AudioSourceConfigDB

app = Flask(__name__)

# Database configuration - requires DATABASE_URL
database_url = os.getenv("DATABASE_URL")
if not database_url:
    print("ERROR: DATABASE_URL environment variable is required", file=sys.stderr)
    sys.exit(1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

def check_radio_receivers():
    """Check radio receiver configurations."""
    print("\n" + "="*80)
    print("STEP 1: Checking Radio Receivers")
    print("="*80)
    
    with app.app_context():
        receivers = RadioReceiver.query.all()
        print(f"\nFound {len(receivers)} radio receiver(s) in database:")
        
        for receiver in receivers:
            print(f"\n  📻 Receiver: {receiver.identifier}")
            print(f"     Display Name: {receiver.display_name}")
            print(f"     Driver: {receiver.driver}")
            print(f"     Frequency: {receiver.frequency_hz/1e6:.3f} MHz")
            print(f"     Sample Rate: {receiver.sample_rate} Hz")
            print(f"     Modulation: {receiver.modulation_type}")
            print(f"     Audio Output: {receiver.audio_output}")
            print(f"     Enabled: {receiver.enabled}")
            print(f"     Auto Start: {receiver.auto_start}")
            
            if not receiver.enabled:
                print(f"     ⚠️  ISSUE: Receiver is DISABLED")
            if not receiver.audio_output:
                print(f"     ⚠️  ISSUE: Audio output is DISABLED")
            if not receiver.auto_start:
                print(f"     ⚠️  WARNING: Auto-start is disabled")
        
        return receivers

def check_audio_sources(receivers):
    """Check audio source configurations for each receiver."""
    print("\n" + "="*80)
    print("STEP 2: Checking Audio Source Configurations")
    print("="*80)
    
    with app.app_context():
        audio_sources = AudioSourceConfigDB.query.filter_by(source_type='sdr').all()
        print(f"\nFound {len(audio_sources)} SDR audio source(s) in database:")
        
        source_by_receiver = {}
        for source in audio_sources:
            config_params = source.config_params or {}
            receiver_id = config_params.get('device_params', {}).get('receiver_id')
            if receiver_id:
                source_by_receiver[receiver_id] = source
            
            print(f"\n  🔊 Audio Source: {source.name}")
            print(f"     Source Type: {source.source_type}")
            print(f"     Enabled: {source.enabled}")
            print(f"     Auto Start: {source.auto_start}")
            print(f"     Managed By: {config_params.get('managed_by')}")
            print(f"     Receiver ID: {receiver_id}")
            print(f"     Sample Rate: {config_params.get('sample_rate')}")
            print(f"     Channels: {config_params.get('channels')}")
            
            if not source.enabled:
                print(f"     ⚠️  ISSUE: Audio source is DISABLED")
            if not source.auto_start:
                print(f"     ⚠️  WARNING: Auto-start is disabled")
            if config_params.get('managed_by') != 'radio':
                print(f"     ⚠️  ISSUE: Not managed by 'radio' - won't use Redis adapter")
        
        # Check for missing audio sources
        print("\n  Checking for missing audio sources:")
        for receiver in receivers:
            if receiver.identifier not in source_by_receiver:
                print(f"    ❌ MISSING: No audio source for receiver '{receiver.identifier}'")
                if receiver.enabled and receiver.audio_output:
                    print(f"       FIX: Receiver is enabled with audio_output=True but no audio source exists!")
            else:
                print(f"    ✅ Found audio source for receiver '{receiver.identifier}'")
        
        return audio_sources

def check_redis_connectivity():
    """Check Redis connectivity and published metrics."""
    print("\n" + "="*80)
    print("STEP 3: Checking Redis Connectivity")
    print("="*80)
    
    try:
        from app_core.redis_client import get_redis_client
        redis_client = get_redis_client()
        
        # Test ping
        redis_client.ping()
        print("\n  ✅ Redis connection successful")
        
        # Check for audio metrics
        print("\n  Checking for audio-service metrics:")
        metrics_raw = redis_client.hgetall("eas:metrics")
        if metrics_raw:
            print(f"    ✅ Found metrics (last update: {len(metrics_raw)} keys)")
            
            # Parse audio controller metrics
            audio_controller_raw = metrics_raw.get(b'audio_controller')
            if audio_controller_raw:
                audio_controller = json.loads(audio_controller_raw)
                sources = audio_controller.get('sources', {})
                active_source = audio_controller.get('active_source')
                
                print(f"\n    Active Source: {active_source}")
                print(f"    Total Sources: {len(sources)}")
                
                for name, stats in sources.items():
                    status = stats.get('status', 'unknown')
                    sample_rate = stats.get('sample_rate')
                    frames = stats.get('frames_captured')
                    print(f"\n      Source: {name}")
                    print(f"        Status: {status}")
                    print(f"        Sample Rate: {sample_rate}")
                    print(f"        Frames Captured: {frames}")
                    
                    if status != 'RUNNING':
                        print(f"        ⚠️  ISSUE: Source is not RUNNING (status={status})")
                    if frames == 0 or frames is None:
                        print(f"        ⚠️  ISSUE: No frames captured")
            else:
                print(f"    ⚠️  No audio_controller metrics found")
            
            # Check EAS monitor metrics
            eas_monitor_raw = metrics_raw.get(b'eas_monitor')
            if eas_monitor_raw:
                eas_monitor = json.loads(eas_monitor_raw)
                running = eas_monitor.get('running', False)
                samples = eas_monitor.get('samples_processed', 0)
                
                print(f"\n    EAS Monitor:")
                print(f"      Running: {running}")
                print(f"      Samples Processed: {samples}")
                
                if not running:
                    print(f"      ❌ ISSUE: EAS monitor is not running!")
                if samples == 0:
                    print(f"      ⚠️  WARNING: No samples processed yet")
            else:
                print(f"    ⚠️  No eas_monitor metrics found")
        else:
            print(f"    ❌ ISSUE: No metrics found in Redis (audio-service may not be running)")
        
        # Check for SDR receiver data
        print("\n  Checking for SDR receiver IQ samples:")
        keys = redis_client.keys("sdr:samples:*")
        if keys:
            print(f"    Found {len(keys)} SDR sample channels:")
            for key in keys:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                receiver_id = key_str.replace('sdr:samples:', '')
                print(f"      📡 {receiver_id}")
        else:
            print(f"    ❌ ISSUE: No SDR sample channels found (sdr-service may not be publishing)")
        
        return True
    
    except Exception as e:
        print(f"\n  ❌ ERROR: Failed to connect to Redis: {e}")
        return False

def check_sdr_service_health():
    """Check if sdr-service is publishing data."""
    print("\n" + "="*80)
    print("STEP 4: Checking SDR Service Health")
    print("="*80)
    
    try:
        from app_core.redis_client import get_redis_client
        redis_client = get_redis_client()
        
        # Subscribe to all sdr:samples:* channels briefly to see if data is flowing
        print("\n  Subscribing to SDR sample channels for 5 seconds...")
        
        pubsub = redis_client.pubsub()
        
        # Get list of receiver IDs
        with app.app_context():
            receivers = RadioReceiver.query.filter_by(enabled=True).all()
            for receiver in receivers:
                channel = f"sdr:samples:{receiver.identifier}"
                pubsub.subscribe(channel)
                print(f"    Subscribed to: {channel}")
        
        # Wait for messages
        messages_received = {}
        start_time = time.time()
        timeout = 5.0
        
        while time.time() - start_time < timeout:
            message = pubsub.get_message(timeout=0.5)
            if message and message['type'] == 'message':
                channel = message['channel'].decode('utf-8') if isinstance(message['channel'], bytes) else message['channel']
                receiver_id = channel.replace('sdr:samples:', '')
                
                if receiver_id not in messages_received:
                    messages_received[receiver_id] = 0
                messages_received[receiver_id] += 1
        
        pubsub.close()
        
        print(f"\n  Results:")
        if messages_received:
            for receiver_id, count in messages_received.items():
                print(f"    ✅ {receiver_id}: Received {count} IQ sample message(s)")
        else:
            print(f"    ❌ ISSUE: No IQ samples received from any receiver!")
            print(f"       - Check if SDR hardware service process is running")
            print(f"       - Check if receivers are started in sdr-service")
            print(f"       - Check sdr-service logs for errors")
        
        return len(messages_received) > 0
    
    except Exception as e:
        print(f"\n  ❌ ERROR: Failed to check SDR service: {e}")
        import traceback
        traceback.print_exc()
        return False

def print_recommendations():
    """Print recommendations based on findings."""
    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)
    
    print("""
To fix the audio chain for LP1, LP2, and SP1:

1. **Ensure Radio Receivers are Properly Configured:**
   - Check that receivers have `enabled=True`
   - Check that receivers have `audio_output=True`
   - Check that receivers have `auto_start=True`

2. **Create Missing Audio Sources:**
   - For each enabled receiver with audio_output=True, there should be an audio source
   - Audio sources should have `source_type='sdr'` and `managed_by='radio'` in config_params
   - Audio sources should have matching `receiver_id` in device_params

3. **Verify SDR Hardware Service is Publishing:**
   - Check if SDR hardware service is running: `systemctl status eas-station-sdr.service`
   - Check service logs: `journalctl -u eas-station-sdr.service -n 100`
   - Verify receivers are started in SDR hardware service

4. **Verify Audio Service is Receiving:**
   - Check if audio service is running: `systemctl status eas-station-audio.service`
   - Check service logs: `journalctl -u eas-station-audio.service -n 100`
   - Look for "✅ Loaded Redis SDR source" messages

5. **Check EAS Monitor:**
   - Verify EAS monitor is subscribed to broadcast queue
   - Check for SAME decoding activity in logs

Run this script again after making changes to verify the fix.
    """)

def main():
    """Main diagnostic routine."""
    print("\n" + "="*80)
    print("EAS STATION - AUDIO CHAIN DIAGNOSTIC")
    print("="*80)
    print("\nThis script will check the complete audio chain from SDR receivers to EAS monitoring.")
    
    try:
        # Step 1: Check radio receivers
        receivers = check_radio_receivers()
        
        # Step 2: Check audio sources
        audio_sources = check_audio_sources(receivers)
        
        # Step 3: Check Redis
        redis_ok = check_redis_connectivity()
        
        # Step 4: Check SDR service
        if redis_ok:
            sdr_ok = check_sdr_service_health()
        
        # Print recommendations
        print_recommendations()
        
        print("\n" + "="*80)
        print("DIAGNOSTIC COMPLETE")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
