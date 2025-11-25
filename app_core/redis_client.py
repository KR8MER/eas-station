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
Robust Redis Client with Retry Logic and Circuit Breaker

Provides centralized Redis connection management with:
- Exponential backoff retry on connection failures
- Circuit breaker pattern to fail fast when Redis is unhealthy
- Connection pooling for better performance
- Health checks to detect connection issues early

Usage:
    from app_core.redis_client import get_redis_client, redis_operation

    # Get client (automatically retries on failure)
    client = get_redis_client()

    # Use circuit breaker for operations
    @redis_operation(max_retries=3)
    def my_redis_op():
        client = get_redis_client()
        return client.get('my_key')
"""

import os
import time
import logging
import functools
from typing import Optional, Any, Callable
from enum import Enum

import redis
from redis import ConnectionError, TimeoutError, RedisError

logger = logging.getLogger(__name__)

# Global Redis client instance
_redis_client: Optional[redis.Redis] = None
_redis_connection_attempts = 0
_last_connection_attempt = 0


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


class CircuitBreaker:
    """
    Circuit breaker for Redis operations.

    Prevents cascading failures by failing fast when Redis is unhealthy.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        success_threshold: int = 2
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before trying again
            success_threshold: Consecutive successes needed to close circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0
        self.state = CircuitState.CLOSED

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            *args, **kwargs: Arguments to pass to function

        Returns:
            Function result

        Raises:
            RedisError: If circuit is open
        """
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                logger.info("Circuit breaker entering HALF_OPEN state (testing recovery)")
                self.state = CircuitState.HALF_OPEN
            else:
                raise RedisError(
                    f"Circuit breaker is OPEN - Redis unhealthy "
                    f"(will retry in {self.recovery_timeout - (time.time() - self.last_failure_time):.1f}s)"
                )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except (ConnectionError, TimeoutError, RedisError) as e:
            self._on_failure()
            raise

    def _on_success(self):
        """Handle successful operation."""
        self.failure_count = 0

        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                logger.info("Circuit breaker CLOSED - Redis recovered")
                self.state = CircuitState.CLOSED
                self.success_count = 0

    def _on_failure(self):
        """Handle failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.success_count = 0

        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                logger.error(
                    f"Circuit breaker OPEN - Redis unhealthy "
                    f"({self.failure_count} failures, will retry in {self.recovery_timeout}s)"
                )
            self.state = CircuitState.OPEN


# Global circuit breaker instance
_circuit_breaker = CircuitBreaker(
    failure_threshold=5,  # Open after 5 failures
    recovery_timeout=30,  # Wait 30s before retry
    success_threshold=2  # Need 2 successes to close
)


def get_redis_client(
    max_retries: int = 5,
    initial_backoff: float = 1.0,
    max_backoff: float = 30.0,
    force_reconnect: bool = False
) -> redis.Redis:
    """
    Get or create Redis client with exponential backoff retry.

    Args:
        max_retries: Maximum connection attempts (0 = unlimited)
        initial_backoff: Initial retry delay in seconds
        max_backoff: Maximum retry delay in seconds
        force_reconnect: Force new connection even if client exists

    Returns:
        Redis client instance

    Raises:
        ConnectionError: If unable to connect after all retries
    """
    global _redis_client, _redis_connection_attempts, _last_connection_attempt

    # Return existing client if healthy
    if _redis_client is not None and not force_reconnect:
        try:
            _redis_client.ping()
            return _redis_client
        except (ConnectionError, TimeoutError, RedisError):
            logger.warning("Existing Redis client unhealthy, reconnecting...")
            _redis_client = None

    # Get connection parameters
    # Default to 'redis' for Docker, not 'localhost' (prevents connection refused errors)
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_db = int(os.getenv("REDIS_DB", "0"))
    redis_password = os.getenv("REDIS_PASSWORD")

    # Retry with exponential backoff
    attempt = 0
    backoff = initial_backoff
    last_error = None

    while max_retries == 0 or attempt < max_retries:
        try:
            # Rate limit connection attempts (max 1 per second)
            time_since_last = time.time() - _last_connection_attempt
            if time_since_last < 1.0:
                time.sleep(1.0 - time_since_last)

            _last_connection_attempt = time.time()
            _redis_connection_attempts += 1

            logger.info(
                f"Connecting to Redis at {redis_host}:{redis_port} "
                f"(attempt {attempt + 1}/{max_retries if max_retries > 0 else '∞'})"
            )

            client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                socket_keepalive=True,
                health_check_interval=30,
                retry_on_timeout=True,
                max_connections=50,
            )

            # Test connection
            client.ping()

            logger.info(f"✅ Redis connected successfully (total attempts: {_redis_connection_attempts})")
            _redis_client = client
            _circuit_breaker.failure_count = 0  # Reset circuit breaker
            return client

        except (ConnectionError, TimeoutError) as e:
            last_error = e
            attempt += 1

            if max_retries > 0 and attempt >= max_retries:
                logger.error(
                    f"❌ Failed to connect to Redis after {max_retries} attempts: {e}"
                )
                raise ConnectionError(
                    f"Unable to connect to Redis at {redis_host}:{redis_port} "
                    f"after {max_retries} attempts: {e}"
                )

            logger.warning(
                f"⚠️  Redis connection failed (attempt {attempt}): {e}. "
                f"Retrying in {backoff:.1f}s..."
            )
            time.sleep(backoff)

            # Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s (max)
            backoff = min(backoff * 2, max_backoff)

    # Should never reach here, but just in case
    raise ConnectionError(f"Unable to connect to Redis: {last_error}")


def redis_operation(
    max_retries: int = 3,
    initial_backoff: float = 0.5,
    use_circuit_breaker: bool = True
):
    """
    Decorator for Redis operations with retry logic and circuit breaker.

    Args:
        max_retries: Maximum retry attempts on transient failures
        initial_backoff: Initial retry delay in seconds
        use_circuit_breaker: Enable circuit breaker protection

    Usage:
        @redis_operation(max_retries=3)
        def get_value(key):
            client = get_redis_client()
            return client.get(key)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Circuit breaker check
            if use_circuit_breaker:
                return _circuit_breaker.call(
                    _retry_operation,
                    func, max_retries, initial_backoff,
                    *args, **kwargs
                )
            else:
                return _retry_operation(
                    func, max_retries, initial_backoff,
                    *args, **kwargs
                )

        return wrapper
    return decorator


def _retry_operation(
    func: Callable,
    max_retries: int,
    initial_backoff: float,
    *args,
    **kwargs
) -> Any:
    """
    Execute Redis operation with retry logic.

    Internal function used by redis_operation decorator.
    """
    attempt = 0
    backoff = initial_backoff
    last_error = None

    while attempt < max_retries:
        try:
            return func(*args, **kwargs)

        except (ConnectionError, TimeoutError) as e:
            last_error = e
            attempt += 1

            if attempt >= max_retries:
                logger.error(f"Redis operation failed after {max_retries} attempts: {e}")
                raise

            logger.warning(
                f"Redis operation failed (attempt {attempt}/{max_retries}): {e}. "
                f"Retrying in {backoff:.1f}s..."
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 5.0)  # Max 5s backoff for operations

    raise last_error


def health_check() -> dict:
    """
    Check Redis connection health.

    Returns:
        Dictionary with health status:
        - healthy: bool
        - latency_ms: float (ping latency)
        - circuit_state: str
        - connection_attempts: int
        - error: str (if unhealthy)
    """
    try:
        client = get_redis_client(max_retries=1)

        # Measure latency
        start = time.time()
        client.ping()
        latency = (time.time() - start) * 1000  # Convert to ms

        return {
            'healthy': True,
            'latency_ms': round(latency, 2),
            'circuit_state': _circuit_breaker.state.value,
            'connection_attempts': _redis_connection_attempts,
        }

    except Exception as e:
        return {
            'healthy': False,
            'latency_ms': None,
            'circuit_state': _circuit_breaker.state.value,
            'connection_attempts': _redis_connection_attempts,
            'error': str(e),
        }


def reset_circuit_breaker():
    """Reset circuit breaker to closed state (for testing)."""
    global _circuit_breaker
    _circuit_breaker.state = CircuitState.CLOSED
    _circuit_breaker.failure_count = 0
    _circuit_breaker.success_count = 0
    logger.info("Circuit breaker manually reset to CLOSED state")
