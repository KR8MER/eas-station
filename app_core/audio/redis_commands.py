"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

"""
Redis Pub/Sub command channel for audio service communication.

This module provides inter-container communication between the web application process
and audio-service process using Redis Pub/Sub.

Architecture:
    web application process → Redis Pub/Sub → audio-service process

Commands:
    - source_start: Start an audio source
    - source_stop: Stop an audio source
    - source_add: Add a new audio source
    - source_update: Update audio source configuration
    - source_delete: Delete an audio source
    - streaming_start: Start auto-streaming service
    - streaming_stop: Stop auto-streaming service
    - eas_monitor_start: Start EAS monitor
    - eas_monitor_stop: Stop EAS monitor
    - inject_test_signal: Inject a synthetic SAME RWT test signal
    - inject_eas_audio: Re-inject a stored EAS WAV into the live air-chain (resend)
    - abort_injected_audio: Purge queued EAS audio from the live air-chain (Hold to Abort)
"""

import json
import logging
import time
from typing import Any, Callable, Dict, Optional

import redis
from app_core.redis_client import get_redis_client
from app_core.config.redis_config import (
    get_redis_host,
    get_redis_port,
    RedisChannels,
    RedisTimeouts,
)

logger = logging.getLogger(__name__)

# Channel names (from centralized config)
AUDIO_COMMAND_CHANNEL = RedisChannels.AUDIO_COMMAND_CHANNEL
AUDIO_RESPONSE_PREFIX = RedisChannels.AUDIO_RESPONSE_PREFIX

# Command timeout (from centralized config)
COMMAND_TIMEOUT = RedisTimeouts.COMMAND_TIMEOUT


class AudioCommandPublisher:
    """
    Publishes audio control commands to Redis for audio-service to execute.

    Used by web application process to send commands to audio-service process.
    """

    def __init__(self):
        """Initialize Redis connection for publishing commands with retry logic."""
        try:
            self.redis_client = get_redis_client(max_retries=5)
            logger.info("✅ AudioCommandPublisher connected to Redis")
        except Exception as e:
            logger.error(f"❌ Failed to connect AudioCommandPublisher to Redis: {e}")
            raise

    def _check_connection(self):
        """Check Redis connection is working."""
        try:
            self.redis_client.ping()
            logger.info(f"AudioCommandPublisher connected to Redis at {get_redis_host()}:{get_redis_port()}")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def _publish_command(self, command: str, params: Dict[str, Any], wait_for_response: bool = False, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Publish a command and optionally wait for response.

        Args:
            command: Command name (e.g., 'source_start')
            params: Command parameters
            wait_for_response: If True, wait for audio-service to respond
            timeout: Response timeout in seconds (only used if wait_for_response=True)

        Returns:
            Response dict with 'success', 'message', and optional 'data'
        """
        command_id = f"{command}_{int(time.time() * 1000)}"

        message = {
            'command_id': command_id,
            'command': command,
            'params': params,
            'timestamp': time.time(),
            'wait_for_response': wait_for_response
        }

        try:
            # Publish command.  PUBLISH returns the number of subscribers that
            # received the message; the audio service's AudioCommandSubscriber
            # is the only one on this channel.  Zero receivers means the audio
            # service is not running, and the command has gone nowhere.
            #
            # Without this check a fire-and-forget command (eas_monitor_start,
            # streaming_start, source_add/update) reported success no matter
            # what: the operator pressed "Start Monitor" against a dead audio
            # service, got no error, and the panel stayed "Unavailable" with
            # nothing explaining why.  A wait-for-response command merely burned
            # its full timeout before saying anything.
            receivers = self.redis_client.publish(AUDIO_COMMAND_CHANNEL, json.dumps(message))

            if not receivers:
                logger.error(
                    "Command %s (id: %s) had no subscribers — the audio service "
                    "is not running", command, command_id
                )
                return {
                    'success': False,
                    'message': (
                        'The audio service is not running, so the command was not '
                        'delivered. Start the eas-station-audio service and try again.'
                    ),
                    'command_id': command_id,
                    'no_subscribers': True,
                }

            logger.info(f"Published command: {command} (id: {command_id}, wait_response: {wait_for_response})")

            if not wait_for_response:
                # Fire-and-forget mode (backward compatible)
                return {
                    'success': True,
                    'message': f'Command {command} sent to audio-service',
                    'command_id': command_id
                }

            # Wait for response mode
            # Create a temporary subscriber to listen for this specific response
            response_key = f"eas:audio:response:{command_id}"
            
            # Poll for response with timeout
            start_time = time.time()
            while time.time() - start_time < timeout:
                response_data = self.redis_client.get(response_key)
                if response_data:
                    # Clean up response key
                    self.redis_client.delete(response_key)
                    
                    try:
                        response = json.loads(response_data)
                        logger.info(f"Command {command} completed: {response.get('message')}")
                        return response
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to decode response for {command_id}: {e}")
                        return {
                            'success': False,
                            'message': f'Invalid response format: {str(e)}',
                            'command_id': command_id
                        }
                
                # Sleep briefly to avoid busy-waiting
                time.sleep(0.1)
            
            # Timeout reached
            logger.warning(f"Command {command} timed out after {timeout}s")
            return {
                'success': False,
                'message': f'Command timed out after {timeout}s - audio-service may be unresponsive',
                'command_id': command_id,
                'timeout': True
            }

        except Exception as e:
            logger.error(f"Failed to publish command {command}: {e}")
            return {
                'success': False,
                'message': f'Failed to send command: {str(e)}'
            }

    def start_source(self, source_name: str, wait_for_response: bool = True) -> Dict[str, Any]:
        """Start an audio source."""
        return self._publish_command('source_start', {'source_name': source_name}, wait_for_response=wait_for_response)

    def stop_source(self, source_name: str, wait_for_response: bool = True) -> Dict[str, Any]:
        """Stop an audio source."""
        return self._publish_command('source_stop', {'source_name': source_name}, wait_for_response=wait_for_response)

    def add_source(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new audio source."""
        return self._publish_command('source_add', {'config': source_config})

    def update_source(self, source_name: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update audio source configuration."""
        return self._publish_command('source_update', {
            'source_name': source_name,
            'updates': updates
        })

    def delete_source(self, source_name: str, wait_for_response: bool = True) -> Dict[str, Any]:
        """Delete an audio source."""
        return self._publish_command('source_delete', {'source_name': source_name}, wait_for_response=wait_for_response)

    def start_streaming(self) -> Dict[str, Any]:
        """Start auto-streaming service."""
        return self._publish_command('streaming_start', {})

    def stop_streaming(self) -> Dict[str, Any]:
        """Stop auto-streaming service."""
        return self._publish_command('streaming_stop', {})

    def start_eas_monitor(self) -> Dict[str, Any]:
        """Start EAS monitor in audio-service."""
        return self._publish_command('eas_monitor_start', {})

    def stop_eas_monitor(self) -> Dict[str, Any]:
        """Stop EAS monitor in audio-service."""
        return self._publish_command('eas_monitor_stop', {})

    def inject_test_signal(self, source_name: Optional[str] = None, timeout: float = 15.0) -> Dict[str, Any]:
        """Inject a SAME RWT test signal into the audio-service EAS pipeline.

        Args:
            source_name: Target a specific source by name.  Pass None to use
                         the first running source.
            timeout: How long to wait for the audio-service to respond (seconds).

        Returns:
            Response dict with 'success', 'message', and optional 'source_name'.
        """
        return self._publish_command(
            'inject_test_signal',
            {'source_name': source_name},
            wait_for_response=True,
            timeout=timeout,
        )

    def inject_eas_audio(self, message_id: int, timeout: float = 20.0) -> Dict[str, Any]:
        """Re-inject a stored EAS message's audio into the live Icecast air-chain.

        Mirrors the live-alert path (``EASBroadcaster.handle_alert`` →
        ``eas_stream_injector.inject_eas_audio``) for a *resend*.  A resend runs
        in a detached subprocess that has no ``AudioIngestController`` and so
        cannot reach the audio-service's in-memory ``BroadcastQueue`` objects
        directly.  This command asks the audio-service process — which owns the
        controller and the running ``IcecastStreamer`` threads — to load the
        stored WAV for *message_id* from the database and inject it, so Icecast
        listeners hear the resent alert just like a fresh broadcast.

        The message id (not the raw audio) is sent over Redis: the audio-service
        already has database access, and every service runs with
        ``PrivateTmp=true`` so a shared temp-file path would not be visible
        across processes.

        Args:
            message_id: Primary key of the ``EASMessage`` to re-inject.
            timeout: How long to wait for the audio-service to confirm injection.

        Returns:
            Response dict with 'success', 'message', and optional 'data'.
        """
        return self._publish_command(
            'inject_eas_audio',
            {'message_id': message_id},
            wait_for_response=True,
            timeout=timeout,
        )

    def inject_raw_eas_audio(self, audio_wav: bytes, timeout: float = 20.0) -> Dict[str, Any]:
        """Inject in-memory WAV bytes into the live Icecast air-chain.

        Sibling of :meth:`inject_eas_audio` for callers that have composite
        audio in hand but no ``EASMessage`` row to reference by id -- namely
        ``webapp/eas/workflow.py``'s manual Send path (which persists a
        ``ManualEASActivation``, not an ``EASMessage``, so it has nothing to
        pass ``inject_eas_audio(message_id=...)``). Manual Send previously
        only played audio locally via the configured ``audio_player_cmd``
        (e.g. ``aplay``) and keyed GPIO -- it never reached Icecast at all,
        so a manually-sent alert (including a Required Weekly Test sent by
        hand) was inaudible to any stream listener. This closes that gap
        using the same base64-in-JSON pattern :meth:`abort_injected_audio`
        already uses for its EOM burst -- fine for a rare, human-triggered
        action; the per-chunk real-time audio path (services/demod) avoids
        this overhead deliberately, this one doesn't need to.

        Args:
            audio_wav: Composite WAV bytes (SAME header + narration + EOM).
            timeout: How long to wait for the audio-service to confirm.

        Returns:
            Response dict with 'success', 'message', and optional 'data'.
        """
        import base64
        return self._publish_command(
            'inject_raw_eas_audio',
            {'audio_b64': base64.b64encode(audio_wav).decode('ascii')},
            wait_for_response=True,
            timeout=timeout,
        )

    def abort_injected_audio(self, eom_wav: Optional[bytes] = None, timeout: float = 10.0) -> Dict[str, Any]:
        """Purge any EAS audio already queued into the live Icecast air-chain.

        Called by ``abort_current_broadcast()`` (the "Hold to Abort
        Broadcast" web button and the physical GPIO Dump/Abort input)
        alongside killing the local playback subprocess -- ``inject_eas_audio``
        pushes a broadcast's audio chunks into each source's
        ``BroadcastQueue`` up front, a separate pipeline the local-subprocess
        kill never touches, so without this an abort left Icecast listeners
        hearing the alert play out to completion regardless of how long the
        button was held.

        Args:
            eom_wav: Optional isolated EOM tone-burst WAV bytes to inject
                immediately after purging, so stream listeners hear a
                compliant sign-off instead of a hard cut to dead air.
                Base64-encoded before sending -- raw bytes are not JSON-safe.
            timeout: How long to wait for the audio-service to confirm.

        Returns:
            Response dict with 'success', 'message', and 'data': {'cleared': int}.
        """
        params: Dict[str, Any] = {}
        if eom_wav:
            import base64
            params['eom_wav_b64'] = base64.b64encode(eom_wav).decode('ascii')
        return self._publish_command(
            'abort_injected_audio',
            params,
            wait_for_response=True,
            timeout=timeout,
        )

    def start_archiver(self, source_name: str, archive_config: Dict[str, Any]) -> Dict[str, Any]:
        """Start archiver for *source_name* in audio-service.

        Args:
            source_name: Name of the audio source to archive.
            archive_config: Dict matching :class:`~app_core.audio.archiver.AudioArchiverConfig`
                            fields (output_dir, segment_duration_seconds, retention_days,
                            max_disk_bytes, format, bitrate).
        """
        return self._publish_command(
            'archiver_start',
            {'source_name': source_name, 'archive_config': archive_config},
        )

    def stop_archiver(self, source_name: str) -> Dict[str, Any]:
        """Stop archiver for *source_name* in audio-service."""
        return self._publish_command('archiver_stop', {'source_name': source_name})


class AudioCommandSubscriber:
    """
    Subscribes to audio control commands and executes them.

    Used by audio-service process to receive and execute commands from app.
    """

    def __init__(self, audio_controller, auto_streaming_service=None, eas_monitor=None,
                 archiver_registry: Optional[Dict[str, Any]] = None, app=None):
        """
        Initialize Redis subscriber with retry logic.

        Args:
            audio_controller: AudioIngestController instance to execute commands on
            auto_streaming_service: Optional AutoStreamingService for Icecast streaming
            eas_monitor: Optional ContinuousEASMonitor for EAS monitoring control
            archiver_registry: Optional dict mapping source_name -> AudioArchiver for
                               handling archiver_start / archiver_stop commands.
            app: Optional Flask app providing database access (used by the
                 ``inject_eas_audio`` command to load a stored EASMessage's WAV).
        """
        self.audio_controller = audio_controller
        self.auto_streaming_service = auto_streaming_service
        self.eas_monitor = eas_monitor
        self.app = app
        self.archiver_registry: Dict[str, Any] = archiver_registry if archiver_registry is not None else {}
        try:
            self.redis_client = get_redis_client(max_retries=5)
            self.pubsub = self.redis_client.pubsub()
            self.running = False
            logger.info("✅ AudioCommandSubscriber connected to Redis")
        except Exception as e:
            logger.error(f"❌ Failed to connect AudioCommandSubscriber to Redis: {e}")
            raise
        self._check_connection()

    def _check_connection(self):
        """Check Redis connection is working."""
        try:
            self.redis_client.ping()
            logger.info(f"AudioCommandSubscriber connected to Redis at {get_redis_host()}:{get_redis_port()}")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def _handle_command(self, message_data: str):
        """
        Handle incoming command message.

        Args:
            message_data: JSON string with command data
        """
        try:
            message = json.loads(message_data)
            command = message.get('command')
            params = message.get('params', {})
            command_id = message.get('command_id')

            if not command or not command_id:
                logger.warning(f"Invalid command message - missing required fields: {message_data[:100]}")
                return

            wait_for_response = message.get('wait_for_response', False)

            logger.info(f"Received command: {command} (id: {command_id}, wait_response: {wait_for_response})")

            # Execute command
            result = self._execute_command(command, params)

            # Publish response if requested
            if wait_for_response:
                response_key = f"eas:audio:response:{command_id}"
                response = {
                    'command_id': command_id,
                    'success': result.get('success', True),
                    'message': result.get('message', 'Command executed'),
                    'data': result.get('data'),
                    'timestamp': time.time()
                }
                # Store response with 30 second TTL
                self.redis_client.setex(response_key, 30, json.dumps(response))
                logger.debug(f"Published response for command {command_id}")
            
            logger.info(f"Command {command} completed: {result}")

        except Exception as e:
            logger.error(f"Error handling command: {e}", exc_info=True)

    def _load_eas_message_audio(self, message_id: Any) -> Optional[bytes]:
        """Load the stored composite WAV for an EASMessage from the database.

        Runs inside an app context so the audio-service process — which only
        holds a minimal Flask app for database access — can read the audio that
        the web process originally generated and persisted.  Returns ``None`` if
        no app is available, the message is missing, or it has no stored audio.
        """
        if self.app is None:
            logger.warning(
                'inject_eas_audio: no Flask app available to load EASMessage #%s', message_id
            )
            return None
        try:
            with self.app.app_context():
                from app_core.models import EASMessage
                message = EASMessage.query.get(int(message_id))
                if message is None:
                    logger.warning('inject_eas_audio: EASMessage #%s not found', message_id)
                    return None
                return message.audio_data or None
        except Exception as exc:
            logger.error('inject_eas_audio: failed to load EASMessage #%s: %s', message_id, exc)
            return None

    def _remove_source_everywhere(self, source_name: str) -> None:
        """Tear down *source_name* from the EAS monitor, Icecast, and the
        audio controller -- the full removal used by both the 'source_delete'
        Redis command and reconcile_orphaned_radio_sources()."""
        if self.eas_monitor and hasattr(self.eas_monitor, 'remove_monitor_for_source'):
            try:
                self.eas_monitor.remove_monitor_for_source(source_name)
            except Exception as e:
                logger.debug(f"Error removing EAS monitor for {source_name}: {e}")

        if self.auto_streaming_service:
            try:
                self.auto_streaming_service.remove_source(source_name)
            except Exception as e:
                logger.debug(f"Error removing {source_name} from Icecast: {e}")

        self.audio_controller.remove_source(source_name)

    def reconcile_orphaned_radio_sources(self) -> int:
        """Remove any radio-managed SDR source with no backing DB row.

        Deleting a RadioReceiver sends a single, best-effort 'source_delete'
        Redis command (webapp/admin/audio_ingest/radio_sources.py) to tear
        the source down here. If that one-shot notification is ever missed
        (this process briefly unreachable, a dropped pub/sub message), the
        source has no other way to learn it should stop existing: it isn't
        in AudioSourceConfigDB any more, but the running RedisSDRSourceAdapter
        stays registered in self.audio_controller and its stall-supervisor
        (app_core/audio/ingest.py's _monitor_loop) just quarantine-retries it
        forever -- since demod service never publishes audio for a receiver
        id nothing references, every retry stalls immediately. Found live:
        an orphaned 'sdr-wxmon' source cycling run/stall/quarantine every
        ~30s-4min, respawning its FFmpeg/Icecast connection each time.

        Called periodically from the main loop (a low-frequency safety net,
        not the primary removal path) so this self-heals within one cycle
        instead of requiring an eas-station-audio.service restart.

        Returns the number of orphaned sources removed.
        """
        from app_core.audio.redis_sdr_adapter import RedisSDRSourceAdapter

        candidates = [
            name for name, adapter in self.audio_controller.get_all_sources().items()
            if isinstance(adapter, RedisSDRSourceAdapter)
        ]
        if not candidates:
            return 0

        if self.app is None:
            return 0

        try:
            with self.app.app_context():
                from app_core.models import AudioSourceConfigDB
                valid_names = {
                    config.name for config in AudioSourceConfigDB.query.filter_by(source_type='sdr').all()
                    if (config.config_params or {}).get('managed_by') == 'radio'
                }
        except Exception as exc:
            logger.debug("reconcile_orphaned_radio_sources: DB lookup failed, skipping: %s", exc)
            return 0

        removed = 0
        for name in candidates:
            if name in valid_names:
                continue
            logger.warning(
                "Removing orphaned radio-managed audio source '%s' -- no "
                "matching enabled receiver/AudioSourceConfigDB row (its "
                "deletion notification was likely missed); self-healing so "
                "it stops quarantine-retrying forever.",
                name,
            )
            try:
                self._remove_source_everywhere(name)
                removed += 1
            except Exception as exc:
                logger.error("Failed to remove orphaned source '%s': %s", name, exc)

        return removed

    def _execute_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a command on the audio controller.

        Args:
            command: Command name
            params: Command parameters

        Returns:
            Result dict with success status and message
        """
        try:
            if command == 'source_start':
                source_name = params['source_name']

                # Check if source exists (may have been skipped if SDR in separated architecture)
                if source_name not in self.audio_controller._sources:
                    logger.info(f"Source '{source_name}' not found - may be SDR source in separated architecture")
                    return {
                        'success': True,
                        'message': f'Source {source_name} not managed by this service',
                        'skipped': True
                    }

                started = self.audio_controller.start_source(source_name)
                if not started:
                    adapter = self.audio_controller._sources.get(source_name)
                    error_detail = (
                        adapter.error_message
                        if adapter and adapter.error_message
                        else "start_source returned False"
                    )
                    logger.error(f"Failed to start source '{source_name}': {error_detail}")
                    return {
                        'success': False,
                        'message': f"Failed to start source '{source_name}': {error_detail}",
                    }

                # Also add source to Icecast streaming if service is available
                if self.auto_streaming_service and self.auto_streaming_service.is_available():
                    try:
                        adapter = self.audio_controller._sources.get(source_name)
                        if adapter:
                            if self.auto_streaming_service.add_source(source_name, adapter):
                                logger.info(f"✅ Added {source_name} to Icecast streaming")
                            else:
                                logger.warning(f"Failed to add {source_name} to Icecast streaming")
                    except Exception as e:
                        logger.warning(f"Error adding {source_name} to Icecast: {e}")

                # Create EAS monitor for newly started source
                if self.eas_monitor and hasattr(self.eas_monitor, 'add_monitor_for_source'):
                    try:
                        if self.eas_monitor.add_monitor_for_source(source_name):
                            logger.info(f"✅ Created EAS monitor for {source_name}")
                        else:
                            logger.warning(f"⚠️ Failed to create EAS monitor for {source_name}")
                    except Exception as e:
                        logger.warning(f"Error creating EAS monitor for {source_name}: {e}")

                return {'success': True, 'message': f'Started source {source_name}'}

            elif command == 'source_stop':
                source_name = params['source_name']

                # Remove EAS monitor for this source
                if self.eas_monitor and hasattr(self.eas_monitor, 'remove_monitor_for_source'):
                    try:
                        self.eas_monitor.remove_monitor_for_source(source_name)
                        logger.info(f"Removed EAS monitor for {source_name}")
                    except Exception as e:
                        logger.debug(f"Error removing EAS monitor for {source_name}: {e}")

                # Remove source from Icecast streaming if service is available
                if self.auto_streaming_service:
                    try:
                        self.auto_streaming_service.remove_source(source_name)
                        logger.info(f"Removed {source_name} from Icecast streaming")
                    except Exception as e:
                        logger.debug(f"Error removing {source_name} from Icecast: {e}")

                self.audio_controller.stop_source(source_name)
                return {'success': True, 'message': f'Stopped source {source_name}'}

            elif command == 'source_add':
                config = params['config']
                source_name = config.get('name')
                source_type_str = config.get('source_type', 'sdr')

                # Import required modules
                from app_core.audio.ingest import AudioSourceConfig, AudioSourceType
                from app_core.audio.sources import create_audio_source

                # Handle redis_sdr as a special case for separated architecture
                # redis_sdr sources subscribe to Redis IQ samples from sdr-service
                if source_type_str == 'redis_sdr':
                    from app_core.audio.redis_sdr_adapter import RedisSDRSourceAdapter
                    
                    # Create runtime configuration for Redis SDR source
                    # Use STREAM type since redis_sdr is not in the AudioSourceType enum
                    runtime_config = AudioSourceConfig(
                        source_type=AudioSourceType.STREAM,  # Use STREAM as placeholder
                        name=source_name,
                        enabled=config.get('enabled', True),
                        priority=config.get('priority', 10),
                        sample_rate=config.get('sample_rate', 44100),
                        channels=config.get('channels', 1),
                        buffer_size=config.get('buffer_size', 4096),
                        silence_threshold_db=config.get('silence_threshold_db', -60.0),
                        silence_duration_seconds=config.get('silence_duration_seconds', 5.0),
                        dead_air_enabled=config.get('dead_air_enabled', False),
                        dead_air_level_threshold_db=config.get('dead_air_level_threshold_db', -65.0),
                        dead_air_detect_open_carrier=config.get('dead_air_detect_open_carrier', True),
                        dead_air_flatness_threshold_pct=config.get('dead_air_flatness_threshold_pct', 25),
                        dead_air_duration_seconds=config.get('dead_air_duration_seconds', 20.0),
                        device_params=config.get('device_params', {}),
                    )

                    # Remove existing source if it exists
                    if source_name in self.audio_controller._sources:
                        if self.auto_streaming_service:
                            try:
                                self.auto_streaming_service.remove_source(source_name)
                            except Exception as e:
                                logger.debug(f"Error removing {source_name} from Icecast: {e}")
                        self.audio_controller.remove_source(source_name)
                    
                    # Create Redis SDR adapter directly
                    adapter = RedisSDRSourceAdapter(runtime_config)
                    self.audio_controller.add_source(adapter)
                    logger.info(f"✅ Added Redis SDR source {source_name} via Redis command")
                    return {'success': True, 'message': f'Redis SDR source {source_name} added'}

                # Create runtime configuration for normal audio source types
                source_type = AudioSourceType(source_type_str)

                # In separated architecture, skip regular SDR sources in audio-service
                # Regular SDR sources require direct hardware access - use redis_sdr instead
                if source_type == AudioSourceType.SDR:
                    # Check if we have radio manager (indicates we can handle SDR)
                    from app_core.extensions import get_radio_manager
                    radio_mgr = get_radio_manager()
                    if not radio_mgr:
                        logger.info(f"⏭️  Skipping SDR source '{source_name}' - no radio manager (handled by sdr-service)")
                        logger.info(f"   Use 'redis_sdr' source type for separated architecture")
                        return {
                            'success': True,
                            'message': f'SDR source {source_name} skipped (no radio manager). Use redis_sdr type for separated architecture.',
                            'skipped': True
                        }

                runtime_config = AudioSourceConfig(
                    source_type=source_type,
                    name=source_name,
                    enabled=config.get('enabled', True),
                    priority=config.get('priority', 10),
                    sample_rate=config.get('sample_rate', 44100),
                    channels=config.get('channels', 1),
                    buffer_size=config.get('buffer_size', 4096),
                    silence_threshold_db=config.get('silence_threshold_db', -60.0),
                    silence_duration_seconds=config.get('silence_duration_seconds', 5.0),
                    dead_air_enabled=config.get('dead_air_enabled', False),
                    dead_air_level_threshold_db=config.get('dead_air_level_threshold_db', -65.0),
                    dead_air_detect_open_carrier=config.get('dead_air_detect_open_carrier', True),
                    dead_air_flatness_threshold_pct=config.get('dead_air_flatness_threshold_pct', 25),
                    dead_air_duration_seconds=config.get('dead_air_duration_seconds', 20.0),
                    device_params=config.get('device_params', {}),
                )

                # Remove existing source if it exists
                if source_name in self.audio_controller._sources:
                    if self.auto_streaming_service:
                        try:
                            self.auto_streaming_service.remove_source(source_name)
                        except Exception as e:
                            logger.debug(f"Error removing {source_name} from Icecast: {e}")
                    self.audio_controller.remove_source(source_name)

                # Create adapter and add to controller
                adapter = create_audio_source(runtime_config)
                self.audio_controller.add_source(adapter)
                logger.info(f"Added audio source {source_name} via Redis command")
                return {'success': True, 'message': f'Source {source_name} added'}

            elif command == 'source_update':
                source_name = params['source_name']
                updates = params['updates']
                self.audio_controller.update_source(source_name, updates)
                return {'success': True, 'message': f'Updated source {source_name}'}

            elif command == 'source_delete':
                source_name = params['source_name']
                self._remove_source_everywhere(source_name)
                return {'success': True, 'message': f'Deleted source {source_name}'}

            elif command == 'streaming_start':
                if self.auto_streaming_service:
                    self.auto_streaming_service.start()
                    return {'success': True, 'message': 'Streaming service started'}
                return {'success': False, 'message': 'Streaming service not available'}

            elif command == 'streaming_stop':
                if self.auto_streaming_service:
                    self.auto_streaming_service.stop()
                    return {'success': True, 'message': 'Streaming service stopped'}
                return {'success': False, 'message': 'Streaming service not available'}

            elif command == 'eas_monitor_start':
                if self.eas_monitor:
                    result = self.eas_monitor.start()
                    if result:
                        return {'success': True, 'message': 'EAS monitor started'}
                    else:
                        return {'success': False, 'message': 'EAS monitor failed to start or already running'}
                return {'success': False, 'message': 'EAS monitor not available'}

            elif command == 'eas_monitor_stop':
                if self.eas_monitor:
                    self.eas_monitor.stop()
                    return {'success': True, 'message': 'EAS monitor stopped'}
                return {'success': False, 'message': 'EAS monitor not available'}

            elif command == 'archiver_start':
                source_name = params.get('source_name')
                archive_config = params.get('archive_config', {})
                if not source_name:
                    return {'success': False, 'message': 'source_name is required'}

                if source_name in self.archiver_registry:
                    return {'success': True, 'message': f'Archiver for {source_name} already running'}

                adapter = self.audio_controller._sources.get(source_name)
                if adapter is None:
                    return {'success': False, 'message': f'Source {source_name} not found'}

                try:
                    from app_core.audio.archiver import AudioArchiver, AudioArchiverConfig

                    cfg = AudioArchiverConfig(
                        output_dir=archive_config.get('output_dir', 'archives'),
                        segment_duration_seconds=int(archive_config.get('segment_duration_seconds', 3600)),
                        retention_days=int(archive_config.get('retention_days', 7)),
                        max_disk_bytes=int(archive_config.get('max_disk_bytes', 0)),
                        format=archive_config.get('format', 'wav'),
                        bitrate=int(archive_config.get('bitrate', 128)),
                        silence_threshold=float(archive_config.get('silence_threshold', 0.0)),
                    )

                    try:
                        broadcast_queue = adapter.get_broadcast_queue()
                    except AttributeError:
                        broadcast_queue = None
                    if broadcast_queue is None:
                        return {'success': False, 'message': f'Source {source_name} has no broadcast queue'}

                    archiver = AudioArchiver(
                        source_name=source_name,
                        config=cfg,
                        broadcast_queue=broadcast_queue,
                        sample_rate=getattr(adapter.config, 'sample_rate', 44100),
                        channels=getattr(adapter.config, 'channels', 1),
                    )
                    if archiver.start():
                        self.archiver_registry[source_name] = archiver
                        return {'success': True, 'message': f'Archiver started for {source_name}'}
                    return {'success': False, 'message': f'Archiver failed to start for {source_name}'}
                except Exception as exc:
                    logger.error('archiver_start error for %s: %s', source_name, exc, exc_info=True)
                    return {'success': False, 'message': str(exc)}

            elif command == 'archiver_stop':
                source_name = params.get('source_name')
                if not source_name:
                    return {'success': False, 'message': 'source_name is required'}

                archiver = self.archiver_registry.pop(source_name, None)
                if archiver:
                    try:
                        archiver.stop()
                    except Exception as exc:
                        logger.warning('archiver_stop error for %s: %s', source_name, exc)
                    return {'success': True, 'message': f'Archiver stopped for {source_name}'}
                return {'success': True, 'message': f'No archiver running for {source_name}'}

            elif command == 'inject_test_signal':
                source_name = params.get('source_name') or None
                # Ensure the EAS monitor has a watcher subscribed to the target
                # source's broadcast queue before publishing the signal.  The
                # UnifiedEASMonitorService discovers sources on a 5-second
                # timer; if the source is newly started there may be no
                # subscriber yet, causing every injected chunk to be dropped.
                if self.eas_monitor and hasattr(self.eas_monitor, '_discover_sources'):
                    try:
                        self.eas_monitor._discover_sources()
                    except Exception as _disc_exc:
                        logger.debug(
                            "EAS monitor pre-injection discovery failed (non-fatal): %s",
                            _disc_exc,
                        )
                used_source = self.audio_controller.inject_eas_test_signal(source_name=source_name)
                if used_source is None:
                    return {'success': False, 'message': 'No running audio source found to inject into'}
                return {
                    'success': True,
                    'message': f"EAS test signal injected into source '{used_source}'",
                    'data': {'source_name': used_source},
                }

            elif command == 'inject_eas_audio':
                message_id = params.get('message_id')
                if not message_id:
                    return {'success': False, 'message': 'message_id is required'}

                wav_bytes = self._load_eas_message_audio(message_id)
                if not wav_bytes:
                    return {
                        'success': False,
                        'message': f'EASMessage #{message_id} has no stored audio',
                        'data': {'injected': False},
                    }

                from app_core.audio.eas_stream_injector import inject_eas_audio as _inject_eas_audio
                injected = _inject_eas_audio(wav_bytes)
                if injected:
                    return {
                        'success': True,
                        'message': 'EAS audio injected into air-chain',
                        'data': {'injected': True},
                    }
                # No running source queues (or no controller) — non-fatal: the
                # resend still keys GPIO and holds the air-chain.  Report it so
                # the caller can log that no Icecast listeners received audio.
                return {
                    'success': False,
                    'message': 'No active source queues to inject into',
                    'data': {'injected': False},
                }

            elif command == 'inject_raw_eas_audio':
                import base64
                audio_b64 = params.get('audio_b64')
                if not audio_b64:
                    return {'success': False, 'message': 'audio_b64 is required'}
                try:
                    wav_bytes = base64.b64decode(audio_b64)
                except Exception as exc:
                    return {'success': False, 'message': f'Invalid audio_b64: {exc}'}
                if not wav_bytes:
                    return {
                        'success': False,
                        'message': 'Decoded audio is empty',
                        'data': {'injected': False},
                    }

                from app_core.audio.eas_stream_injector import inject_eas_audio as _inject_eas_audio
                injected = _inject_eas_audio(wav_bytes)
                if injected:
                    return {
                        'success': True,
                        'message': 'EAS audio injected into air-chain',
                        'data': {'injected': True},
                    }
                return {
                    'success': False,
                    'message': 'No active source queues to inject into',
                    'data': {'injected': False},
                }

            elif command == 'abort_injected_audio':
                eom_wav = None
                eom_wav_b64 = params.get('eom_wav_b64')
                if eom_wav_b64:
                    import base64
                    try:
                        eom_wav = base64.b64decode(eom_wav_b64)
                    except Exception as exc:
                        logger.warning('abort_injected_audio: failed to decode EOM audio: %s', exc)

                from app_core.audio.eas_stream_injector import abort_injected_audio as _abort_injected_audio
                cleared = _abort_injected_audio(replacement_wav=eom_wav)
                return {
                    'success': True,
                    'message': f'Cleared {cleared} queued EAS audio chunk(s)',
                    'data': {'cleared': cleared},
                }

            else:
                return {'success': False, 'message': f'Unknown command: {command}'}

        except Exception as e:
            logger.error(f"Error executing command {command}: {e}", exc_info=True)
            return {'success': False, 'message': str(e)}

    def start(self):
        """Start listening for commands."""
        self.pubsub.subscribe(AUDIO_COMMAND_CHANNEL)
        self.running = True

        logger.info(f"AudioCommandSubscriber listening on channel: {AUDIO_COMMAND_CHANNEL}")

        for message in self.pubsub.listen():
            if not self.running:
                break

            if message['type'] == 'message':
                self._handle_command(message['data'])

    def stop(self):
        """Stop listening for commands."""
        self.running = False
        self.pubsub.unsubscribe(AUDIO_COMMAND_CHANNEL)
        self.pubsub.close()
        logger.info("AudioCommandSubscriber stopped")


# Global publisher instance for web application process
_publisher: Optional[AudioCommandPublisher] = None


def get_audio_command_publisher() -> AudioCommandPublisher:
    """
    Get global AudioCommandPublisher instance.

    Returns:
        AudioCommandPublisher instance
    """
    global _publisher
    if _publisher is None:
        _publisher = AudioCommandPublisher()
    return _publisher
