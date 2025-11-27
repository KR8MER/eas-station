"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

This module provides inter-container communication between the app container
and audio-service container using Redis Pub/Sub.

Architecture:
    app container → Redis Pub/Sub → audio-service container

Commands:
    - source_start: Start an audio source
    - source_stop: Stop an audio source
    - source_add: Add a new audio source
    - source_update: Update audio source configuration
    - source_delete: Delete an audio source
    - streaming_start: Start auto-streaming service
    - streaming_stop: Stop auto-streaming service
"""

import json
import logging
import os
import time
from typing import Any, Callable, Dict, Optional

import redis
from app_core.redis_client import get_redis_client, redis_operation

logger = logging.getLogger(__name__)

# Channel names
AUDIO_COMMAND_CHANNEL = 'eas:audio:commands'
AUDIO_RESPONSE_CHANNEL = 'eas:audio:responses'

# Command timeout (seconds)
COMMAND_TIMEOUT = 30


class AudioCommandPublisher:
    """
    Publishes audio control commands to Redis for audio-service to execute.

    Used by app container to send commands to audio-service container.
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
            logger.info(f"AudioCommandPublisher connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def _publish_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Publish a command and wait for response.

        Args:
            command: Command name (e.g., 'source_start')
            params: Command parameters

        Returns:
            Response dict with 'success', 'message', and optional 'data'
        """
        command_id = f"{command}_{int(time.time() * 1000)}"

        message = {
            'command_id': command_id,
            'command': command,
            'params': params,
            'timestamp': time.time()
        }

        try:
            # Publish command
            self.redis_client.publish(AUDIO_COMMAND_CHANNEL, json.dumps(message))
            logger.info(f"Published command: {command} (id: {command_id})")

            # For now, return success immediately
            # TODO: Implement response waiting mechanism if needed
            return {
                'success': True,
                'message': f'Command {command} sent to audio-service',
                'command_id': command_id
            }

        except Exception as e:
            logger.error(f"Failed to publish command {command}: {e}")
            return {
                'success': False,
                'message': f'Failed to send command: {str(e)}'
            }

    def start_source(self, source_name: str) -> Dict[str, Any]:
        """Start an audio source."""
        return self._publish_command('source_start', {'source_name': source_name})

    def stop_source(self, source_name: str) -> Dict[str, Any]:
        """Stop an audio source."""
        return self._publish_command('source_stop', {'source_name': source_name})

    def add_source(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new audio source."""
        return self._publish_command('source_add', {'config': source_config})

    def update_source(self, source_name: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update audio source configuration."""
        return self._publish_command('source_update', {
            'source_name': source_name,
            'updates': updates
        })

    def delete_source(self, source_name: str) -> Dict[str, Any]:
        """Delete an audio source."""
        return self._publish_command('source_delete', {'source_name': source_name})

    def start_streaming(self) -> Dict[str, Any]:
        """Start auto-streaming service."""
        return self._publish_command('streaming_start', {})

    def stop_streaming(self) -> Dict[str, Any]:
        """Stop auto-streaming service."""
        return self._publish_command('streaming_stop', {})


class AudioCommandSubscriber:
    """
    Subscribes to audio control commands and executes them.

    Used by audio-service container to receive and execute commands from app.
    """

    def __init__(self, audio_controller, auto_streaming_service=None):
        """
        Initialize Redis subscriber with retry logic.

        Args:
            audio_controller: AudioIngestController instance to execute commands on
            auto_streaming_service: Optional AutoStreamingService for Icecast streaming
        """
        self.audio_controller = audio_controller
        self.auto_streaming_service = auto_streaming_service
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
            logger.info(f"AudioCommandSubscriber connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
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
            command = message['command']
            params = message['params']
            command_id = message['command_id']

            logger.info(f"Received command: {command} (id: {command_id})")

            # Execute command
            result = self._execute_command(command, params)

            logger.info(f"Command {command} completed: {result}")

        except Exception as e:
            logger.error(f"Error handling command: {e}", exc_info=True)

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
                self.audio_controller.start_source(source_name)
                
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
                
                return {'success': True, 'message': f'Started source {source_name}'}

            elif command == 'source_stop':
                source_name = params['source_name']
                
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
                self.audio_controller.add_source(**config)
                return {'success': True, 'message': 'Source added'}

            elif command == 'source_update':
                source_name = params['source_name']
                updates = params['updates']
                self.audio_controller.update_source(source_name, updates)
                return {'success': True, 'message': f'Updated source {source_name}'}

            elif command == 'source_delete':
                source_name = params['source_name']
                
                # Remove source from Icecast streaming if service is available
                if self.auto_streaming_service:
                    try:
                        self.auto_streaming_service.remove_source(source_name)
                    except Exception as e:
                        logger.debug(f"Error removing {source_name} from Icecast: {e}")
                
                self.audio_controller.remove_source(source_name)
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


# Global publisher instance for app container
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
