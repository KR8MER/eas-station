# Audio Playout Queue System

## Overview

The Audio Playout Queue system provides FCC-compliant, priority-based alert playback for the EAS Station. It implements the precedence requirements specified in 47 CFR Part 11 to ensure that higher-priority alerts (such as Presidential National Emergency Messages) automatically preempt lower-priority alerts.

## Key Features

- **FCC-Compliant Precedence**: Implements 47 CFR Section 11.31 precedence requirements
- **Priority Queue**: Automatic sorting by precedence, severity, urgency, and timestamp
- **Preemption Support**: High-priority alerts automatically interrupt lower-priority playback
- **Deterministic Playback**: Background service ensures reliable, ordered alert playback
- **Event Tracking**: Complete audit trail of all playout events for compliance reporting
- **Thread-Safe**: Designed for concurrent access from multiple sources
- **Backward Compatible**: Existing code continues to work with immediate playback mode

## Architecture

### Components

1. **AudioPlayoutQueue** (`app_core/audio/playout_queue.py`)
   - Thread-safe priority queue for alert management
   - Automatic priority calculation based on FCC precedence rules
   - Queue state tracking (queued, playing, completed)

2. **AudioOutputService** (`app_core/audio/output_service.py`)
   - Background worker thread for deterministic playback
   - Audio subprocess management (aplay, ffplay, etc.)
   - GPIO relay control for transmitter activation
   - Playout event logging

3. **EASBroadcaster Integration** (`app_utils/eas.py`)
   - Optional queue mode in addition to immediate playback
   - Backward compatible with existing deployments
   - Automatic enqueuing of alerts with precedence calculation

4. **Storage Helpers** (`app_core/eas_storage.py`)
   - Precedence determination utilities
   - Statistical analysis functions
   - Event enrichment for reporting

## FCC Precedence Levels

The system implements the following precedence hierarchy (highest to lowest):

### 1. Presidential (EAN)
- **Event Code**: EAN
- **Description**: Presidential National Emergency Message
- **Behavior**: **MUST** preempt all other alerts immediately
- **47 CFR Requirement**: Absolute priority

### 2. Nationwide Test (NPT)
- **Event Code**: NPT
- **Description**: Nationwide Test of the Emergency Alert System
- **Behavior**: High priority, preempts operational alerts

### 3. Local Alerts
- **Scope**: Public, local events
- **Description**: Local emergency alerts (tornadoes, floods, etc.)
- **Behavior**: Higher priority than state/regional/national alerts

### 4. State/Regional Alerts
- **Event Codes**: SPW, EVI, CEM, DMO, etc.
- **Description**: State or regional emergency alerts
- **Behavior**: Higher priority than national non-Presidential alerts

### 5. National Alerts
- **Scope**: Public, national events (non-Presidential)
- **Description**: National-level alerts that are not Presidential
- **Behavior**: Lower priority than local/state alerts

### 6. Test Alerts
- **Event Codes**: RMT (Required Monthly Test), RWT (Required Weekly Test)
- **Description**: Regular test transmissions
- **Behavior**: Lowest operational priority

### Within Each Precedence Level

Alerts are further prioritized by:
1. **Severity**: Extreme > Severe > Moderate > Minor > Unknown
2. **Urgency**: Immediate > Expected > Future > Past > Unknown
3. **Timestamp**: Older alerts play first

## Usage

### Basic Setup (Queue Mode)

```python
from app_core.audio import AudioPlayoutQueue, AudioOutputService
from app_utils.eas import EASBroadcaster, load_eas_config

# Create queue
queue = AudioPlayoutQueue(logger=app.logger)

# Create output service
config = load_eas_config()
service = AudioOutputService(
    queue=queue,
    config=config,
    logger=app.logger,
    gpio_controller=gpio,  # Optional
)

# Start background playout worker
service.start()

# Create broadcaster with queue
broadcaster = EASBroadcaster(
    db_session=db.session,
    model_cls=EASMessage,
    config=config,
    logger=app.logger,
    playout_queue=queue,  # Enable queue mode
)

# Handle alerts - they will be automatically enqueued
result = broadcaster.handle_alert(alert, payload)

if result.get('should_interrupt'):
    # High-priority alert detected
    # AudioOutputService will automatically handle preemption
    pass

# Stop service on shutdown
service.stop()
```

### Legacy Mode (Immediate Playback)

```python
# Create broadcaster WITHOUT queue (existing behavior)
broadcaster = EASBroadcaster(
    db_session=db.session,
    model_cls=EASMessage,
    config=config,
    logger=app.logger,
    # No playout_queue parameter = immediate mode
)

# Alerts play synchronously, blocking the caller
result = broadcaster.handle_alert(alert, payload)
```

### Queue Status Monitoring

```python
# Get queue status
status = queue.get_status()
print(f"Queue size: {status['queue_size']}")
print(f"Current item: {status['current_item']}")
print(f"Next item: {status['next_item']}")

# Get service status
service_status = service.get_status()
print(f"Service running: {service_status['running']}")
print(f"Recent events: {service_status['recent_events']}")

# Get queue snapshot for display
snapshot = queue.get_queue_snapshot()
for item in snapshot:
    print(f"Alert {item['event_code']}: precedence={item['precedence_level']}")
```

### Event Callbacks

```python
from app_core.audio import PlayoutEvent, PlayoutStatus

def on_playout_event(event: PlayoutEvent):
    """Called for each playout event."""
    if event.status == PlayoutStatus.COMPLETED:
        print(f"Alert {event.item.event_code} played successfully")
    elif event.status == PlayoutStatus.FAILED:
        print(f"Alert {event.item.event_code} failed: {event.error}")
    elif event.status == PlayoutStatus.INTERRUPTED:
        print(f"Alert {event.item.event_code} was preempted")

# Register callback
service.register_event_callback(on_playout_event)
```

## Configuration

### Environment Variables

The queue system uses the existing EAS configuration:

```bash
# Enable EAS broadcasting
EAS_BROADCAST_ENABLED=true

# Audio player command
EAS_AUDIO_PLAYER="aplay -D default"

# GPIO relay control (optional)
EAS_GPIO_PIN=17
EAS_GPIO_ACTIVE_STATE=HIGH
EAS_GPIO_HOLD_SECONDS=5

# Output directory
EAS_OUTPUT_DIR=/path/to/audio/files
```

### Queue-Specific Configuration

```python
# Configure queue behavior
queue = AudioPlayoutQueue(logger=logger)

# Service configuration
service = AudioOutputService(
    queue=queue,
    config=config,
    logger=logger,
    gpio_controller=gpio,  # Optional GPIO control
)
```

## Database Integration

### EASMessage Storage

The queue system works seamlessly with the existing `EASMessage` model. When an alert is enqueued:

1. Audio files are generated as usual
2. `EASMessage` record is created in the database
3. `PlayoutItem` is created with reference to the `EASMessage`
4. Item is added to the priority queue
5. Background service plays the alert
6. Playout events are tracked in metadata

### Playout Event Tracking

The `AudioOutputService` generates playout events that can be stored in the `metadata_payload` field of `EASMessage`:

```python
{
    "playout_events": [
        {
            "timestamp": "2025-11-05T12:00:00Z",
            "status": "pending",
            "target": "local_audio"
        },
        {
            "timestamp": "2025-11-05T12:00:01Z",
            "status": "playing",
            "target": "local_audio"
        },
        {
            "timestamp": "2025-11-05T12:00:15Z",
            "status": "completed",
            "target": "local_audio",
            "latency_ms": 14523.5
        }
    ]
}
```

## Precedence Examples

### Example 1: Presidential Alert Preempts Everything

```text
Initial Queue:
1. Tornado Warning (LOCAL, EXTREME, IMMEDIATE) - currently playing
2. Severe Thunderstorm Warning (LOCAL, SEVERE, IMMEDIATE) - queued

New Alert: Presidential National Emergency (EAN)
Result:
- Tornado warning playback INTERRUPTED immediately
- Presidential alert plays NOW
- Tornado warning re-queued
- Severe thunderstorm warning remains queued

Final Queue:
1. Tornado Warning (LOCAL, EXTREME, IMMEDIATE)
2. Severe Thunderstorm Warning (LOCAL, SEVERE, IMMEDIATE)
```

### Example 2: Severity-Based Priority

```text
Queue:
1. Flood Advisory (LOCAL, MINOR, EXPECTED)

New Alert 1: Tornado Warning (LOCAL, EXTREME, IMMEDIATE)
New Alert 2: Severe Thunderstorm Warning (LOCAL, SEVERE, IMMEDIATE)
New Alert 3: Dense Fog Advisory (LOCAL, MINOR, EXPECTED)

Result (ordered by precedence, severity, urgency):
1. Tornado Warning (EXTREME) - plays immediately
2. Severe Thunderstorm Warning (SEVERE) - plays next
3. Flood Advisory (MINOR) - plays next
4. Dense Fog Advisory (MINOR) - plays last
```

### Example 3: Test vs. Operational Alerts

```text
Queue:
1. Required Monthly Test (RMT) - currently playing

New Alert: Tornado Warning (LOCAL, EXTREME, IMMEDIATE)
Result:
- RMT playback INTERRUPTED
- Tornado warning plays immediately
- RMT is NOT re-queued (tests don't resume after interruption)
```

## Compliance & Reporting

### Precedence Statistics

```python
from app_core.eas_storage import get_precedence_statistics

# Get precedence distribution for recent alerts
alerts = CAPAlert.query.filter(
    CAPAlert.sent >= datetime.now(timezone.utc) - timedelta(days=30)
).all()

stats = get_precedence_statistics(alerts)
print(stats)
# {
#     'available': True,
#     'precedence_distribution': {
#         'LOCAL': 45,
#         'STATE': 12,
#         'TEST': 8,
#         'NATIONAL': 2
#     },
#     'severity_distribution': {
#         'SEVERE': 32,
#         'MODERATE': 20,
#         'MINOR': 15
#     },
#     'urgency_distribution': {
#         'IMMEDIATE': 28,
#         'EXPECTED': 24,
#         'FUTURE': 15
#     },
#     'total_alerts': 67
# }
```

### Playout Event Enrichment

```python
from app_core.eas_storage import enrich_playout_events_with_precedence

# Enrich playout events with precedence info
alerts_by_id = {alert.id: alert for alert in alerts}
enriched_events = enrich_playout_events_with_precedence(
    events=playout_events,
    alerts_by_id=alerts_by_id,
)

for event in enriched_events:
    print(f"Alert {event['alert_id']}: {event['precedence']} - {event['severity']}")
```

## Testing

### Unit Tests

```python
import pytest
from app_core.audio import AudioPlayoutQueue, PlayoutItem, PrecedenceLevel

def test_presidential_alert_priority():
    """Test that Presidential alerts have highest priority."""
    queue = AudioPlayoutQueue()

    # Create test items
    tornado = PlayoutItem(
        precedence_level=PrecedenceLevel.LOCAL,
        severity=1,
        urgency=1,
        timestamp=time.time(),
        queue_id=1,
        event_code='TOR',
    )

    presidential = PlayoutItem(
        precedence_level=PrecedenceLevel.PRESIDENTIAL,
        severity=1,
        urgency=1,
        timestamp=time.time() + 100,  # Newer timestamp
        queue_id=2,
        event_code='EAN',
    )

    # Enqueue in reverse priority order
    queue.enqueue(tornado)
    queue.enqueue(presidential)

    # Presidential should come out first despite newer timestamp
    first = queue.dequeue()
    assert first.event_code == 'EAN'

    second = queue.dequeue()
    assert second.event_code == 'TOR'
```

### Integration Tests

```python
def test_queue_with_broadcaster():
    """Test queue integration with EASBroadcaster."""
    queue = AudioPlayoutQueue()

    broadcaster = EASBroadcaster(
        db_session=db.session,
        model_cls=EASMessage,
        config=config,
        logger=logger,
        playout_queue=queue,
    )

    # Handle an alert
    result = broadcaster.handle_alert(alert, payload)

    assert result['queued'] == True
    assert result['queue_id'] is not None
    assert queue.size == 1
```

## Migration Guide

### From Immediate to Queue Mode

1. **Create Queue and Service**:
```python
queue = AudioPlayoutQueue(logger=app.logger)
service = AudioOutputService(queue=queue, config=config, logger=app.logger)
service.start()
```

2. **Update Broadcaster**:
```python
# Old:
broadcaster = EASBroadcaster(db.session, EASMessage, config, logger)

# New:
broadcaster = EASBroadcaster(
    db.session, EASMessage, config, logger,
    playout_queue=queue  # Add this
)
```

3. **Update Shutdown**:
```python
# Add service shutdown
service.stop()
```

### Gradual Migration

You can run both modes simultaneously:

```python
# Queue mode for automated CAP alerts
queue_broadcaster = EASBroadcaster(..., playout_queue=queue)

# Immediate mode for manual activations
immediate_broadcaster = EASBroadcaster(...)  # No queue

# Route appropriately
if alert_source == 'cap':
    queue_broadcaster.handle_alert(alert, payload)
else:
    immediate_broadcaster.handle_alert(alert, payload)
```

## Troubleshooting

### Queue Not Processing Alerts

1. Check that `AudioOutputService` is started:
```python
status = service.get_status()
assert status['running'] == True
```

2. Check queue size:
```python
print(f"Queue size: {queue.size}")
```

3. Check audio player configuration:
```python
assert config.get('audio_player_cmd') is not None
```

### Alerts Playing Out of Order

1. Verify precedence calculation:
```python
from app_core.eas_storage import determine_alert_precedence
precedence = determine_alert_precedence(alert)
print(f"Alert precedence: {precedence}")
```

2. Check alert metadata:
```python
print(f"Event code: {alert.event}")
print(f"Severity: {alert.severity}")
print(f"Urgency: {alert.urgency}")
print(f"Scope: {alert.scope}")
```

### Preemption Not Working

1. Check if preemption is enabled:
```python
should_interrupt = queue.enqueue(item, check_preemption=True)
```

2. Verify priority comparison:
```python
current = queue.current_item
next_item = queue.peek()
should_preempt = queue._should_preempt(next_item, current)
print(f"Should preempt: {should_preempt}")
```

## Performance Considerations

- **Queue Size**: The queue is unbounded but typically contains < 10 items
- **Memory Usage**: Each `PlayoutItem` is ~1KB; 100 items = ~100KB
- **Thread Safety**: All operations use RLock for thread safety
- **Background Worker**: Runs in a separate daemon thread
- **Audio Playback**: Subprocess-based, one alert at a time

## Future Enhancements

- [ ] Multiple output targets (local audio + streaming)
- [ ] Parallel playback support
- [ ] Audio mixing for simultaneous alerts
- [ ] Web UI for queue monitoring
- [ ] REST API for queue control
- [ ] Database-backed queue persistence
- [ ] Alert batching for efficiency
- [ ] Advanced scheduling (time-based delays)

## References

- [47 CFR Part 11 - Emergency Alert System](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-11)
- [FCC EAS Operating Handbook](https://www.fcc.gov/general/eas-operating-handbook)
- [SAME Protocol Specification](https://en.wikipedia.org/wiki/Specific_Area_Message_Encoding)

## Support

For questions or issues with the Audio Playout Queue system:

1. Check this documentation
2. Review the code comments in `app_core/audio/`
3. Check the logs for error messages
4. Open a GitHub issue with details

## License

Same as the main EAS Station project.
