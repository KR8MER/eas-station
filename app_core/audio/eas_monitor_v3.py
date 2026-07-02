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
Unified EAS Monitor Service - V3 Architecture

CRITICAL REDESIGN: Single-threaded unified monitor service that addresses
inefficiencies in the multi-monitor architecture.

Previous Architecture (V2):
- N separate monitor threads (one per audio source)
- Manual monitor lifecycle management (add/remove monitors)
- Status aggregation overhead on every API call
- Duplicate resources (N resampling adapters, N health trackers)
- Tight coupling to audio source lifecycle

New Architecture (V3):
- Single monitor thread for ALL audio sources
- Auto-discovery of running sources
- Centralized health tracking
- Shared SAME decoder for all sources
- Lightweight per-source watchers (no threads)

Benefits:
- 1 thread instead of N threads → reduced CPU/memory
- No manual lifecycle management → simpler code
- Direct status access → no aggregation overhead
- Centralized health → consistent tracking
- Auto-discovery → decoupled from source lifecycle

Architecture:

    UnifiedEASMonitorService (1 thread)
    ├── SourceWatcher[LP1] (subscribes to LP1 broadcast queue)
    ├── SourceWatcher[LP2] (subscribes to LP2 broadcast queue)
    ├── SourceWatcher[SP1] (subscribes to SP1 broadcast queue)
    ├── HealthTracker (centralized health for all sources)
    └── StreamingSAMEDecoder (shared decoder processing all sources)

Usage:
    from app_core.audio.eas_monitor_v3 import UnifiedEASMonitorService
    
    # Initialize with audio controller reference
    monitor = UnifiedEASMonitorService(
        audio_controller=audio_controller,
        alert_callback=my_alert_handler,
        configured_fips_codes=['012345', '067890']
    )
    
    # Start unified monitor (auto-discovers sources)
    monitor.start()
    
    # Get status (no aggregation needed)
    status = monitor.get_status()
    
    # Stop when done
    monitor.stop()
"""

import logging
import threading
import time
import queue
import io
import wave
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime

import numpy as np

from app_utils import utc_now
from .streaming_same_decoder import StreamingSAMEDecoder
from .broadcast_adapter import BroadcastAudioAdapter  # Changed from ResamplingBroadcastAdapter
from .broadcast_queue import BroadcastQueue

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ring-buffer helpers
# ---------------------------------------------------------------------------

def _zczc_ring_position(ring_total_now: int, sample_rate: int) -> int:
    """Return the ring-buffer position to use as the ZCZC anchor point.

    The streaming decoder fires the ZCZC callback at the END of burst 1
    (after the last character of the header has been decoded).  Recording
    from that point means only bursts 2 and 3 appear in the stored audio.

    Back-tracking by 1.5 s ensures the full burst 1 — preamble (≈ 0.25 s)
    plus message body (≈ 1.0–1.2 s) — is included, so all three bursts are
    present in the stored recording and available for 2-of-3 voting.

    Args:
        ring_total_now: Monotonic ring sample counter at callback time.
        sample_rate:    Ring buffer sample rate (typically 16 000 Hz).

    Returns:
        Adjusted ring position (never negative).
    """
    backtrack = int(1.5 * sample_rate)   # ≈ 24 000 samples @ 16 kHz
    return max(0, ring_total_now - backtrack)


# =============================================================================
# Health Tracking
# =============================================================================

@dataclass
class SourceHealth:
    """Health metrics for a single audio source."""
    source_name: str
    last_audio_time: float = 0.0
    consecutive_empty_reads: int = 0
    consecutive_successful_reads: int = 0  # Track recovery from no-audio state
    samples_processed: int = 0
    audio_flowing: bool = False
    last_error: Optional[str] = None
    error_count: int = 0


class HealthTracker:
    """
    Centralized health tracking for all monitored audio sources.

    Tracks per-source health metrics and provides aggregated health status.
    Thread-safe for concurrent updates from monitor thread.

    Uses hysteresis to prevent state bouncing:
    - Requires RECOVERY_THRESHOLD consecutive successful reads before marking as flowing
    - Requires TIMEOUT_THRESHOLD seconds without audio before marking as not flowing
    """

    # Hysteresis thresholds to prevent rapid state changes
    RECOVERY_THRESHOLD = 10  # Consecutive successful reads needed to recover from not-flowing state

    def __init__(self, audio_timeout_seconds: float = 5.0):
        """
        Initialize health tracker.

        Args:
            audio_timeout_seconds: Time without audio before marking source unhealthy
        """
        self._sources: Dict[str, SourceHealth] = {}
        self._lock = threading.Lock()
        self._audio_timeout_seconds = audio_timeout_seconds
        self._start_time = time.time()
        
    def register_source(self, source_name: str) -> None:
        """Register a new source for health tracking."""
        with self._lock:
            if source_name not in self._sources:
                self._sources[source_name] = SourceHealth(source_name=source_name)
                logger.debug(f"Registered source '{source_name}' in health tracker")
    
    def unregister_source(self, source_name: str) -> None:
        """Unregister a source from health tracking."""
        with self._lock:
            if source_name in self._sources:
                del self._sources[source_name]
                logger.debug(f"Unregistered source '{source_name}' from health tracker")
    
    def update_audio_received(self, source_name: str, sample_count: int) -> None:
        """
        Record that audio was received from a source.

        Uses hysteresis to prevent rapid state changes:
        - If already flowing: keeps flowing state
        - If not flowing: requires RECOVERY_THRESHOLD consecutive successful reads
          before transitioning back to flowing state
        """
        with self._lock:
            if source_name in self._sources:
                health = self._sources[source_name]
                health.last_audio_time = time.time()
                health.consecutive_empty_reads = 0
                health.samples_processed += sample_count

                # Apply hysteresis when recovering from not-flowing state
                if health.audio_flowing:
                    # Already flowing - keep it that way
                    health.consecutive_successful_reads = 0  # Reset recovery counter
                else:
                    # Not currently flowing - count consecutive successful reads
                    health.consecutive_successful_reads += 1
                    if health.consecutive_successful_reads >= self.RECOVERY_THRESHOLD:
                        # Enough consecutive successful reads - mark as flowing
                        health.audio_flowing = True
                        logger.info(
                            f"Source '{source_name}' audio flowing restored after "
                            f"{health.consecutive_successful_reads} consecutive successful reads"
                        )
                        health.consecutive_successful_reads = 0
    
    def update_no_audio(self, source_name: str) -> None:
        """
        Record that no audio was available from a source.

        Marks source as not flowing if audio timeout is exceeded.
        Only resets the recovery counter when audio has been genuinely absent
        for more than 1 second; brief queue-empty returns (normal between
        chunks) must not interrupt consecutive-read counting.
        """
        with self._lock:
            if source_name in self._sources:
                health = self._sources[source_name]
                health.consecutive_empty_reads += 1

                # Determine how long we have truly been without audio
                if health.last_audio_time > 0:
                    time_since_audio = time.time() - health.last_audio_time
                else:
                    time_since_audio = float('inf')

                # Only reset the recovery counter when audio has been absent
                # for more than 1 second.  Brief timeouts between audio chunks
                # (e.g. 100 ms queue poll with chunks arriving every ~85 ms)
                # should not prevent the audio_flowing flag from being set.
                if time_since_audio > 1.0:
                    health.consecutive_successful_reads = 0

                # Check if audio timeout exceeded
                if time_since_audio > self._audio_timeout_seconds:
                    if health.audio_flowing:
                        # Transitioning from flowing to not flowing
                        logger.warning(
                            f"Source '{source_name}' audio stopped flowing "
                            f"(no audio for {time_since_audio:.1f}s, {health.consecutive_empty_reads} empty reads)"
                        )
                    health.audio_flowing = False
    
    def update_error(self, source_name: str, error_msg: str) -> None:
        """Record an error for a source."""
        with self._lock:
            if source_name in self._sources:
                health = self._sources[source_name]
                health.error_count += 1
                health.last_error = error_msg
                health.consecutive_empty_reads = 0
                health.consecutive_successful_reads = 0  # Reset recovery counter on error
    
    def get_source_health(self, source_name: str) -> Optional[SourceHealth]:
        """Get health metrics for a specific source."""
        with self._lock:
            return self._sources.get(source_name)
    
    def get_all_health(self) -> Dict[str, SourceHealth]:
        """Get health metrics for all sources."""
        with self._lock:
            return dict(self._sources)
    
    def get_active_source_count(self) -> int:
        """Get count of sources with flowing audio."""
        with self._lock:
            return sum(1 for h in self._sources.values() if h.audio_flowing)
    
    def get_total_samples_processed(self) -> int:
        """Get total samples processed across all sources."""
        with self._lock:
            return sum(h.samples_processed for h in self._sources.values())
    
    def get_uptime_seconds(self) -> float:
        """Get tracker uptime in seconds."""
        return time.time() - self._start_time


# =============================================================================
# Source Watcher
# =============================================================================

class SourceWatcher:
    """
    Lightweight per-source audio subscriber with dedicated SAME decoder.

    This is NOT a separate thread - it's just a subscriber to a source's
    broadcast queue. The UnifiedEASMonitorService polls all watchers in
    its single monitoring thread.

    Each watcher owns its own StreamingSAMEDecoder so that audio from
    different sources is never interleaved into the same FSK demodulator.
    Interleaving audio from LP1 and LP2 into a shared decoder destroys the
    coherent 520.83 baud FSK signal required for SAME header detection.

    Responsibilities:
    - Subscribe to source's broadcast queue
    - Buffer audio chunks for consumption
    - Decode audio through a dedicated SAME decoder
    - Track basic per-source stats
    """

    def __init__(
        self,
        source_name: str,
        eas_broadcast_queue: BroadcastQueue,  # Now expects 16kHz queue directly
        alert_callback: Optional[Callable] = None,
    ):
        """
        Initialize source watcher with its own SAME decoder.

        ARCHITECTURAL FIX: Now receives pre-resampled 16kHz audio from dedicated EAS queue.
        No more resampling needed - eliminates conversion bottleneck and reduces memory by 3x.

        Each watcher creates its own StreamingSAMEDecoder so that audio from
        this source is never mixed with audio from other sources inside the decoder.

        Args:
            source_name: Name of the audio source
            eas_broadcast_queue: Source's 16kHz EAS broadcast queue (pre-resampled)
            alert_callback: Function to call when a SAME alert is detected
        """
        self.source_name = source_name
        self.source_sample_rate = 16000  # Always 16kHz now
        self.target_sample_rate = 16000

        # Subscribe directly to 16kHz queue - no resampling needed!
        subscriber_id = f"eas-unified-{source_name}"
        self._adapter = BroadcastAudioAdapter(
            broadcast_queue=eas_broadcast_queue,
            subscriber_id=subscriber_id,
            sample_rate=16000,
            read_timeout=0.1  # Short timeout so one stalled source doesn't block others
        )

        # Dedicated per-source SAME decoder.
        # CRITICAL: do NOT share a decoder across sources.  The SAME header is
        # a ~1-second 520.83-baud FSK burst.  Interleaving 100ms chunks from
        # two different sources resets the DLL every cycle and prevents detection.
        self._decoder = StreamingSAMEDecoder(
            sample_rate=16000,
            alert_callback=alert_callback,
        )

        logger.info(
            f"SourceWatcher initialized for '{source_name}': "
            f"16kHz pre-resampled queue, dedicated SAME decoder"
        )

    def read_audio(self, num_samples: int) -> Optional[np.ndarray]:
        """
        Read audio samples from this source.

        Args:
            num_samples: Number of samples to read at target rate

        Returns:
            NumPy array of samples, or None if no audio available
        """
        try:
            return self._adapter.read_audio(num_samples)
        except Exception as e:
            logger.error(f"Error reading audio from '{self.source_name}': {e}")
            return None

    def process_samples(self, samples: np.ndarray) -> None:
        """Feed audio samples into this source's dedicated SAME decoder."""
        self._decoder.process_samples(samples)

    def get_decoder_stats(self) -> Dict[str, Any]:
        """Return stats from this source's SAME decoder."""
        return self._decoder.get_stats()

    def get_stats(self) -> Dict[str, Any]:
        """Get adapter statistics."""
        if hasattr(self._adapter, 'get_stats'):
            return self._adapter.get_stats()
        return {}


# =============================================================================
# Unified EAS Monitor Service
# =============================================================================

class UnifiedEASMonitorService:
    """
    Single-threaded unified EAS monitor service.
    
    Monitors ALL audio sources in a single thread using lightweight
    SourceWatcher subscribers. Automatically discovers and tracks
    running audio sources.
    
    This replaces the multi-monitor architecture where each source
    had its own monitor thread. Benefits:
    - 1 thread instead of N threads
    - Auto-discovery of sources (no manual add/remove)
    - Centralized health tracking
    - No status aggregation overhead
    - Shared SAME decoder
    
    The monitor thread polls all source watchers in round-robin fashion,
    processing audio from each source and feeding it to a shared SAME
    decoder. Alert callbacks include source identification.
    """
    
    def __init__(
        self,
        audio_controller,
        alert_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        configured_fips_codes: Optional[List[str]] = None,
        discovery_interval_seconds: float = 5.0,
        chunk_duration_ms: int = 100
    ):
        """
        Initialize unified EAS monitor service.
        
        Args:
            audio_controller: AudioSourceController instance for source discovery
            alert_callback: Function to call when alert detected
            configured_fips_codes: List of FIPS codes for filtering (None = accept all)
            discovery_interval_seconds: How often to check for new/removed sources
            chunk_duration_ms: Audio chunk size in milliseconds
        """
        self.audio_controller = audio_controller
        self.alert_callback = alert_callback
        self.configured_fips_codes = configured_fips_codes or []
        self._discovery_interval = discovery_interval_seconds
        self._chunk_duration_ms = chunk_duration_ms
        
        # Calculate chunk size at 16kHz (SAME decoder rate)
        self._target_sample_rate = 16000
        self._chunk_size = int(self._target_sample_rate * chunk_duration_ms / 1000)
        
        # Source watchers: {source_name: SourceWatcher}
        self._watchers: Dict[str, SourceWatcher] = {}
        self._watchers_lock = threading.Lock()
        
        # Health tracking
        self._health_tracker = HealthTracker(audio_timeout_seconds=5.0)

        # NOTE: No shared decoder here.  Each SourceWatcher owns its own
        # StreamingSAMEDecoder.  Sharing one decoder across sources caused
        # interleaved audio (100ms LP1 / 100ms LP2 / ...) to corrupt the FSK
        # demodulator state, preventing SAME header detection entirely.

        # State management
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._start_time: Optional[float] = None
        self._last_discovery_time = 0.0

        # Statistics
        self._total_alerts_detected = 0   # ZCZC header count (may be 3× per event)
        self._total_alerts_dispatched = 0  # EOM-confirmed dispatch count (one per event)
        self._last_alert_dispatch_time: Optional[float] = None  # Unix timestamp of last dispatch

        # Per-source audio capture buffers for OTA alert recording.
        #
        # Two distinct capacity regimes share the same deque per source:
        #
        #   • Idle (no pending alert)  → small rolling pre-roll
        #     Keeps ~10 s of recent audio so the ZCZC back-track (1.5 s) and
        #     the three SAME header bursts (~4.8 s) are available when a
        #     header is decoded.  Old chunks are evicted continuously.
        #
        #   • Active capture (between ZCZC decode and EOM/timeout) → no eviction
        #     The deque grows to hold the full alert.  Capped at
        #     _capture_max_samples (matches _eom_timeout_seconds) as a safety
        #     net so a stuck capture can't grow without bound.
        self._preroll_max_seconds = 10
        self._preroll_max_samples = self._target_sample_rate * self._preroll_max_seconds
        self._audio_rings: Dict[str, deque] = {}
        self._audio_rings_lock = threading.Lock()

        # Sources with an active ZCZC → EOM capture in progress.  Guarded by
        # _audio_rings_lock so the monitor loop can decide trim policy without
        # acquiring a second lock.
        self._capturing_sources: set[str] = set()

        # Monotonic per-source sample counter (never wraps back, not bounded by the
        # ring capacity).  Used to determine exactly how many samples were added to
        # the ring AFTER the ZCZC header was decoded so we can slice out the
        # attention-signal + voice-narration audio when the EOM arrives.
        self._ring_total_added: Dict[str, int] = {}

        # EOM-gated forwarding state.
        # When a ZCZC header is decoded we park the alert dict here and record the
        # ring's total-samples counter.  The alert is only forwarded (with the
        # captured narration audio attached) once the matching NNNN EOM is decoded.
        # If no EOM arrives within _eom_timeout_seconds the alert is forwarded
        # anyway so real emergencies are never silently dropped.
        self._pending_alerts: Dict[str, Dict] = {}     # source → alert dict
        self._zczc_ring_total: Dict[str, int] = {}     # source → ring total at ZCZC
        self._pending_lock = threading.Lock()
        self._eom_timeout_seconds: float = 300.0       # 5-minute safety net

        # Hard ceiling on active-capture buffer size, matched to the EOM
        # timeout so a stuck capture can't grow without bound.  Includes a
        # small headroom (+10 s) to cover the pre-roll already in the deque
        # when ZCZC fires.
        self._capture_max_samples = int(
            self._target_sample_rate * (self._eom_timeout_seconds + 10)
        )

        logger.info(
            f"UnifiedEASMonitorService initialized: "
            f"chunk={chunk_duration_ms}ms ({self._chunk_size} samples at 16kHz), "
            f"FIPS codes={len(self.configured_fips_codes)}, "
            f"discovery_interval={discovery_interval_seconds}s"
        )
    
    def start(self) -> bool:
        """Start the unified monitor service."""
        if self._running:
            logger.warning("UnifiedEASMonitorService already running")
            return False
        
        logger.info("Starting UnifiedEASMonitorService...")
        
        # Initial source discovery
        self._discover_sources()
        
        # Start monitoring thread
        self._running = True
        self._start_time = time.time()
        
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="eas-unified-monitor",
            daemon=True
        )
        self._thread.start()
        
        logger.info(
            f"✅ UnifiedEASMonitorService started monitoring {len(self._watchers)} source(s)"
        )
        return True
    
    def stop(self) -> None:
        """Stop the unified monitor service."""
        if not self._running:
            return
        
        logger.info("Stopping UnifiedEASMonitorService...")
        self._running = False
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("UnifiedEASMonitorService thread did not stop cleanly")
        
        # Clean up watchers
        with self._watchers_lock:
            watcher_count = len(self._watchers)
            self._watchers.clear()
        
        logger.info(
            f"✅ UnifiedEASMonitorService stopped. "
            f"Processed audio from {watcher_count} source(s), "
            f"dispatched {self._total_alerts_dispatched} alert(s) "
            f"({self._total_alerts_detected} ZCZC header burst(s) decoded)"
        )
    
    def _discover_sources(self) -> None:
        """
        Discover running audio sources and create/remove watchers.
        
        This implements auto-discovery by querying the audio controller
        for running sources and comparing with our current watchers.
        """
        from app_core.audio.ingest import AudioSourceStatus
        
        try:
            # Get currently running sources from audio controller
            running_sources = {}
            for source_name, source_adapter in self.audio_controller._sources.items():
                if source_adapter.status == AudioSourceStatus.RUNNING:
                    running_sources[source_name] = source_adapter
            
            with self._watchers_lock:
                current_watchers = set(self._watchers.keys())
                discovered_sources = set(running_sources.keys())
                
                # Add watchers for new sources
                sources_to_add = discovered_sources - current_watchers
                for source_name in sources_to_add:
                    self._add_watcher(source_name, running_sources[source_name])
                
                # Remove watchers for stopped sources
                sources_to_remove = current_watchers - discovered_sources
                for source_name in sources_to_remove:
                    self._remove_watcher(source_name)
                
                if sources_to_add or sources_to_remove:
                    logger.info(
                        f"Source discovery: +{len(sources_to_add)} -{len(sources_to_remove)} "
                        f"(now monitoring {len(self._watchers)} sources)"
                    )
        
        except Exception as e:
            logger.error(f"Error during source discovery: {e}", exc_info=True)
    
    def _add_watcher(self, source_name: str, source_adapter) -> None:
        """Add a watcher for a new source (called with lock held)."""
        try:
            # ARCHITECTURAL FIX: Get the 16kHz EAS broadcast queue
            # This queue contains pre-resampled audio, eliminating conversion bottleneck
            eas_broadcast_queue = source_adapter.get_eas_broadcast_queue()

            # Build a per-source alert callback that tags the source name before
            # forwarding to the unified monitor's _handle_alert.  Using a closure
            # over source_name means the correct source is identified even when
            # the decoder fires asynchronously (relative to the polling loop).
            def _per_source_alert(alert_data, _sname=source_name):
                self._handle_alert(alert_data, source_name=_sname)

            # Create watcher with its own dedicated SAME decoder
            watcher = SourceWatcher(
                source_name=source_name,
                eas_broadcast_queue=eas_broadcast_queue,
                alert_callback=_per_source_alert,
            )

            self._watchers[source_name] = watcher
            self._health_tracker.register_source(source_name)

            logger.info(f"✅ Added watcher for source '{source_name}' (16kHz pre-resampled queue, dedicated decoder)")
        
        except Exception as e:
            logger.error(f"Failed to add watcher for '{source_name}': {e}", exc_info=True)
    
    def _remove_watcher(self, source_name: str) -> None:
        """Remove a watcher for a stopped source (called with lock held)."""
        watcher = self._watchers.pop(source_name, None)
        if watcher:
            self._health_tracker.unregister_source(source_name)
            logger.info(f"✅ Removed watcher for source '{source_name}'")
    
    def _handle_alert(self, alert_data, source_name: Optional[str] = None) -> None:
        """
        Handle a decoded SAME message from a per-source decoder.

        The decoder fires this for BOTH ZCZC (header) and NNNN (EOM) messages.

        ZCZC: park the alert as pending and record the ring position — do NOT
              forward yet.  The attention tone and voice narration haven't arrived.
        NNNN: extract the narration audio captured since ZCZC, attach it to the
              pending alert, then forward.
        """
        from .streaming_same_decoder import StreamingSAMEAlert
        from .eas_monitor import _same_alert_to_dict
        if isinstance(alert_data, StreamingSAMEAlert):
            raw_msg = alert_data.message or ''
            alert_data = _same_alert_to_dict(alert_data)
        else:
            raw_msg = (alert_data or {}).get('raw_header', '') if isinstance(alert_data, dict) else ''

        effective_source = source_name or 'unknown'
        if isinstance(alert_data, dict):
            alert_data['source_name'] = effective_source

        # If this alert was injected synthetically by inject_eas_test_signal(),
        # the decoded signal is known-clean FSK — override confidence to 1.0.
        if isinstance(alert_data, dict) and 'ZCZC' in raw_msg:
            ctrl = self.audio_controller
            synthetic_headers = getattr(ctrl, '_synthetic_headers', None)
            synthetic_lock = getattr(ctrl, '_synthetic_headers_lock', None)
            if synthetic_headers is not None and raw_msg.strip() in synthetic_headers:
                alert_data['confidence'] = 1.0
                if synthetic_lock is not None:
                    with synthetic_lock:
                        synthetic_headers.discard(raw_msg.strip())
                else:
                    synthetic_headers.discard(raw_msg.strip())
                logger.debug(
                    "Synthetic injection detected for '%s' — setting confidence=100%%",
                    raw_msg[:60],
                )

        if 'NNNN' in raw_msg:
            # EOM received — fire any pending alert for this source.
            self._on_eom_received(effective_source)
            return

        if 'ZCZC' not in raw_msg:
            # Unknown message type (shouldn't happen); ignore.
            return

        # ── ZCZC SAME header ──────────────────────────────────────────────────
        self._total_alerts_detected += 1

        # Snapshot the ring's monotonic total so we know where "post-ZCZC" begins.
        with self._audio_rings_lock:
            ring_total_now = self._ring_total_added.get(effective_source, 0)

        with self._pending_lock:
            same_event_pending = effective_source in self._pending_alerts
            if same_event_pending:
                existing_event = self._pending_alerts[effective_source].get('event_code', '?')
                new_event = alert_data.get('event_code', '?')
                if existing_event != new_event:
                    # Different event code — a new distinct alert; replace ring reference too.
                    logger.warning(
                        "New ZCZC from '%s' replaced un-EOM'd pending alert (%s → %s)",
                        effective_source, existing_event, new_event,
                    )
                    self._zczc_ring_total[effective_source] = _zczc_ring_position(
                        ring_total_now, self._target_sample_rate
                    )
                else:
                    # Same event code — this is burst #2 or #3 of the same header
                    # transmission.  Update the decoded alert data but keep the ring
                    # position from burst #1 so that ATTENTION_SKIP_SAMPLES is
                    # measured from the earliest known point and we don't clip the
                    # narration start.
                    # Preserve the highest confidence seen across all bursts so the
                    # stored record reflects the best-quality decode, not the last one.
                    existing_confidence = self._pending_alerts[effective_source].get('confidence', 0.0)
                    new_confidence = alert_data.get('confidence', 0.0)
                    best_confidence = max(existing_confidence, new_confidence)
                    logger.debug(
                        "SAME burst #2/#3 from '%s' for %s — "
                        "confidence prev=%.1f%% new=%.1f%% best=%.1f%%",
                        effective_source, new_event,
                        existing_confidence * 100, new_confidence * 100, best_confidence * 100,
                    )
                    alert_data['confidence'] = best_confidence
                    # (ring total intentionally NOT updated here)
            else:
                # First burst for this source — record ring position, backed up by
                # ~1.5 s so the full burst 1 (preamble ≈ 0.25 s + message ≈ 1.0 s)
                # is included in the stored audio.  Without this back-track the
                # callback fires at the END of burst 1, leaving only bursts 2 and 3
                # in the captured recording.
                self._zczc_ring_total[effective_source] = _zczc_ring_position(
                    ring_total_now, self._target_sample_rate
                )
            alert_data['_pending_since'] = time.time()
            self._pending_alerts[effective_source] = alert_data

        # Mark this source as actively capturing so the monitor loop stops
        # trimming its ring buffer until EOM arrives.  Done outside the
        # _pending_lock to preserve the existing lock ordering
        # (_audio_rings_lock acquired before _pending_lock elsewhere).
        with self._audio_rings_lock:
            self._capturing_sources.add(effective_source)

        logger.warning(
            "🔔 SAME header from '%s': %s — holding until EOM before forwarding",
            effective_source, alert_data.get('event_code', 'UNKNOWN'),
        )

    def _on_eom_received(self, source_name: str) -> None:
        """EOM (NNNN) received: attach captured narration audio and forward the alert."""
        with self._pending_lock:
            alert_data = self._pending_alerts.pop(source_name, None)
            zczc_total = self._zczc_ring_total.pop(source_name, None)

        # Allow the monitor loop to resume trimming this source's ring back
        # down to the pre-roll size now that the capture is complete.  The
        # ring snapshot taken below is unaffected — list(ring) copies the
        # deque structure before any further trims could occur.
        with self._audio_rings_lock:
            self._capturing_sources.discard(source_name)

        if alert_data is None:
            logger.debug("EOM from '%s' with no pending alert — ignoring", source_name)
            return

        # ── Extract post-ZCZC audio from the ring ─────────────────────────────
        # Layout since ZCZC decode fires (at end of first ~1 s burst):
        #   ~4.8 s  three SAME bursts + inter-burst silences
        #   ~0.5 s  pause before attention tone
        #   8–25 s  attention tone (EAS 853+960 Hz or EBS 1050 Hz)
        #   ──────
        #   narration follows immediately after the tone ends
        #
        # We detect the actual tone end via _find_narration_start() instead of
        # using a hard-coded skip, so alerts with short/long or missing tones
        # are handled correctly.  EOM_TRIM_SAMPLES removes the leading NNNN FSK
        # burst that appears at the very end of the ring buffer.
        EOM_TRIM_SAMPLES = int(self._target_sample_rate * 2)    # 2 s safety trim

        with self._audio_rings_lock:
            ring = self._audio_rings.get(source_name)
            ring_total_now = self._ring_total_added.get(source_name, 0)

        if ring and zczc_total is not None:
            try:
                combined = np.concatenate(list(ring)).astype(np.float32)
                samples_since_zczc = max(0, min(ring_total_now - zczc_total, len(combined)))

                # The newest samples_since_zczc samples are those captured after ZCZC.
                post_zczc = combined[-samples_since_zczc:] if samples_since_zczc > 0 else combined[:0]

                # Full post-ZCZC audio → raw_audio_wav (database storage / playback).
                if len(post_zczc) > 0:
                    alert_data['raw_audio_wav'] = _encode_wav_bytes(
                        post_zczc, self._target_sample_rate
                    )

                # Detect where the attention tone ends so we can slice out
                # just the voice narration for the relay broadcast.
                attention_skip = _find_narration_start(post_zczc, self._target_sample_rate)

                # Slice out the narration for the relay broadcast.
                narration = post_zczc[attention_skip:]
                if EOM_TRIM_SAMPLES > 0 and len(narration) > EOM_TRIM_SAMPLES:
                    narration = narration[:-EOM_TRIM_SAMPLES]

                min_narration_samples = self._target_sample_rate  # ≥ 1 second
                if len(narration) >= min_narration_samples:
                    alert_data['relay_audio_wav'] = _encode_wav_bytes(
                        narration, self._target_sample_rate
                    )
                    logger.info(
                        "Captured %.1f s narration audio from '%s' for relay "
                        "(tone ended at %.1f s)",
                        len(narration) / self._target_sample_rate,
                        source_name,
                        attention_skip / self._target_sample_rate,
                    )

                    # Assess the captured narration for gate-chopping (upstream
                    # ENDEC/processor stutter).  The result is stored on the
                    # alert so the forwarding path can substitute local TTS
                    # (EASSettings.relay_narration_source) and so operators can
                    # see the verdict on the received-alert detail page.
                    try:
                        from app_utils.audio_quality import assess_narration_quality
                        quality = assess_narration_quality(
                            narration, self._target_sample_rate
                        )
                        if quality is not None:
                            alert_data['narration_quality'] = quality
                            if quality['degraded']:
                                logger.warning(
                                    "Off-air narration from '%s' is gate-chopped: "
                                    "%.1f dropout events/min, %.0f%% silence — the "
                                    "stutter is present in the received signal",
                                    source_name,
                                    quality['gate_events_per_minute'],
                                    quality['silence_fraction'] * 100,
                                )
                    except Exception as _quality_exc:
                        logger.debug(
                            "Narration quality assessment failed: %s", _quality_exc
                        )

                # Always relay with the standard EAS dual-tone (853+960 Hz, 8 s)
                # regardless of what the originating station transmitted:
                #   • NOAA sends 1050 Hz  → strip, replace with EAS dual-tone
                #   • Sender sends EBS dual-tone → relay as EAS dual-tone
                # The tone duration is fixed at 8 s per FCC §11.31(a).
                alert_data['relay_tone_profile'] = 'attention'   # 853 + 960 Hz
                alert_data['relay_tone_duration'] = 8.0

            except Exception as _exc:
                logger.warning("Could not encode OTA narration audio: %s", _exc)

        # Derive a correlation ID from the raw SAME header so detection and
        # forwarding log lines share a key.
        from app_core.logging_context import push_alert, pop_alert
        import hashlib as _hashlib
        _corr_id = alert_data.get('identifier')
        if not _corr_id:
            seed = alert_data.get('raw_header') or alert_data.get('raw_text') or ''
            if seed:
                _corr_id = (
                    f"OTA-{alert_data.get('event_code', 'UNK')}-"
                    f"{_hashlib.sha1(seed.encode('utf-8', 'ignore')).hexdigest()[:8]}"
                )
            else:
                _corr_id = f"OTA-{source_name}-{alert_data.get('event_code', 'UNK')}"
            alert_data['identifier'] = _corr_id

        _token = push_alert(_corr_id)
        try:
            logger.warning(
                "🚨 EOM from '%s' — forwarding %s alert",
                source_name, alert_data.get('event_code', 'UNKNOWN'),
            )

            self._total_alerts_dispatched += 1
            self._last_alert_dispatch_time = time.time()

            if self.alert_callback:
                try:
                    self.alert_callback(alert_data)
                except Exception as e:
                    logger.error("Error in alert callback: %s", e, exc_info=True)
        finally:
            pop_alert(_token)

    def _monitor_loop(self) -> None:
        """
        Main monitoring loop (single thread for all sources).
        
        This is the core of the unified architecture. It:
        1. Periodically discovers new/removed sources
        2. Polls each source watcher in round-robin fashion
        3. Processes audio through shared SAME decoder
        4. Updates centralized health tracking
        """
        logger.info("UnifiedEASMonitorService monitor loop starting...")
        
        while self._running:
            try:
                # Periodic source discovery
                current_time = time.time()
                if current_time - self._last_discovery_time >= self._discovery_interval:
                    self._discover_sources()
                    self._last_discovery_time = current_time
                
                # Get current watchers (snapshot to avoid holding lock)
                with self._watchers_lock:
                    watchers_snapshot = list(self._watchers.items())
                
                # If no watchers, sleep and continue
                if not watchers_snapshot:
                    time.sleep(0.1)
                    continue
                
                # Poll each source watcher
                any_audio_processed = False
                for source_name, watcher in watchers_snapshot:
                    try:
                        # Try to read audio from this source
                        samples = watcher.read_audio(self._chunk_size)

                        if samples is not None and len(samples) > 0:
                            # Update per-source ring buffer BEFORE decoding so the
                            # audio is available if the decoder fires an alert callback
                            # synchronously during process_samples().
                            with self._audio_rings_lock:
                                ring = self._audio_rings.setdefault(source_name, deque())
                                ring.append(samples.copy())
                                # Monotonic counter: never reset, used to slice post-ZCZC audio
                                self._ring_total_added[source_name] = (
                                    self._ring_total_added.get(source_name, 0) + len(samples)
                                )
                                # Trim policy depends on whether a ZCZC → EOM capture
                                # is currently in progress for this source.  Idle
                                # sources keep only a short pre-roll; active captures
                                # grow until EOM (capped at _capture_max_samples as
                                # a runaway safety net).
                                if source_name in self._capturing_sources:
                                    max_samples = self._capture_max_samples
                                else:
                                    max_samples = self._preroll_max_samples
                                total = sum(len(c) for c in ring)
                                while total > max_samples and ring:
                                    total -= len(ring.popleft())

                            # Process audio through this source's OWN dedicated decoder.
                            # This is the key fix: each source has its own FSK demodulator
                            # so their audio streams are never interleaved in the same DLL.
                            watcher.process_samples(samples)

                            # Update health tracking
                            self._health_tracker.update_audio_received(
                                source_name,
                                len(samples)
                            )

                            any_audio_processed = True
                        else:
                            # No audio available from this source
                            self._health_tracker.update_no_audio(source_name)

                    except Exception as e:
                        logger.error(
                            f"Error processing audio from '{source_name}': {e}",
                            exc_info=True
                        )
                        self._health_tracker.update_error(source_name, str(e))
                
                # Only sleep when no audio was processed (idle sources).
                # When audio IS flowing, read_audio() already provides natural
                # rate-limiting via blocking queue.get() calls.  Adding a fixed
                # 50ms sleep here causes the consumer to fall behind the producer
                # by ~15% per cycle, filling the 10000-chunk broadcast queue in
                # ~7 hours and introducing up to 15+ minutes of EAS detection
                # latency — preventing real-time SAME header detection entirely.
                if not any_audio_processed:
                    time.sleep(0.05)  # 50ms when idle — no urgency, save CPU

                # EOM timeout: if a pending alert has waited too long without an
                # EOM (e.g. EOM burst was missed), forward it anyway so it isn't
                # silently dropped.
                now_ts = time.time()
                with self._pending_lock:
                    timed_out = [
                        src for src, data in self._pending_alerts.items()
                        if now_ts - data.get('_pending_since', now_ts) >= self._eom_timeout_seconds
                    ]
                for src in timed_out:
                    logger.warning(
                        "EOM timeout for source '%s' — forwarding pending alert without narration audio",
                        src,
                    )
                    self._on_eom_received(src)
            
            except Exception as e:
                logger.error(f"Error in unified monitor loop: {e}", exc_info=True)
                time.sleep(0.1)
        
        logger.info("UnifiedEASMonitorService monitor loop exited")
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get comprehensive status for the unified monitor.

        Returns status in format compatible with MultiMonitorManager
        for backward compatibility with existing API consumers.
        """
        # CRITICAL FIX: Capture watchers FIRST, then calculate health based on CURRENT watchers
        # This prevents race where health_percentage is from old sources but monitor_count is 0
        monitors_status = {}
        # Aggregate decoder stats across all per-watcher decoders
        agg_decoder_synced = False
        agg_decoder_in_message = False
        agg_decoder_bytes_decoded = 0

        with self._watchers_lock:
            # Capture these while lock is held - prevents race with _discover_sources()
            monitor_count = len(self._watchers)
            source_names = list(self._watchers.keys())
            # Collect per-watcher decoder stats while we hold the lock
            per_watcher_decoder_stats = {
                sn: w.get_decoder_stats() for sn, w in self._watchers.items()
            }

        # Aggregate decoder stats
        for stats in per_watcher_decoder_stats.values():
            if stats.get('synced'):
                agg_decoder_synced = True
            if stats.get('in_message'):
                agg_decoder_in_message = True
            agg_decoder_bytes_decoded += stats.get('bytes_decoded', 0)

        # Now get health ONLY for currently registered watchers
        # This ensures health metrics match current watcher state
        all_health = self._health_tracker.get_all_health()
        uptime = self._health_tracker.get_uptime_seconds()

        # Calculate aggregates based on CURRENT watchers (not stale health data)
        total_samples = 0
        active_sources = 0
        for source_name in source_names:
            health = all_health.get(source_name)
            if health:
                total_samples += health.samples_processed
                if health.audio_flowing:
                    active_sources += 1

        # Calculate health percentage from current watcher data
        if uptime > 0 and total_samples > 0 and active_sources > 0:
            samples_per_second = total_samples / uptime
            expected_rate = self._target_sample_rate * active_sources
            health_percentage = min(1.0, samples_per_second / expected_rate)
        else:
            samples_per_second = 0
            health_percentage = 0.0

        # Build per-source status for current watchers
        with self._watchers_lock:
            for source_name, watcher in self._watchers.items():
                health = all_health.get(source_name)
                if health:
                    time_since_audio = (
                        time.time() - health.last_audio_time
                        if health.last_audio_time > 0
                        else 999999
                    )

                    source_samples_per_sec = (
                        health.samples_processed / uptime
                        if uptime > 0
                        else 0
                    )

                    dec_stats = per_watcher_decoder_stats.get(source_name, {})
                    monitors_status[source_name] = {
                        "running": self._running,
                        "mode": "unified-streaming",
                        "source_name": source_name,
                        "audio_flowing": health.audio_flowing,
                        "samples_processed": health.samples_processed,
                        "samples_per_second": int(source_samples_per_sec),
                        "time_since_last_audio": time_since_audio,
                        "consecutive_empty_reads": health.consecutive_empty_reads,
                        "error_count": health.error_count,
                        "last_error": health.last_error,
                        "sample_rate": self._target_sample_rate,
                        "source_sample_rate": watcher.source_sample_rate,
                        "decoder_synced": dec_stats.get('synced', False),
                        "decoder_in_message": dec_stats.get('in_message', False),
                        "decoder_bytes_decoded": dec_stats.get('bytes_decoded', 0),
                    }

        # Return status in MultiMonitorManager-compatible format
        # Use captured values to avoid race condition with _discover_sources()
        return {
            "running": self._running,
            "mode": "unified-streaming",
            "samples_processed": total_samples,
            "wall_clock_runtime_seconds": uptime,
            "runtime_seconds": total_samples / self._target_sample_rate if total_samples > 0 else 0,
            "samples_per_second": int(samples_per_second),
            "alerts_detected": self._total_alerts_dispatched,  # EOM-confirmed events
            "alerts_detected_zczc": self._total_alerts_detected,  # raw ZCZC count (up to 3× per event)
            "last_alert_time": self._last_alert_dispatch_time,  # Unix timestamp, None if never
            "monitor_count": monitor_count,  # Use captured value
            "active_sources": active_sources,
            "audio_flowing": active_sources > 0,
            "health_percentage": health_percentage,
            "source_names": source_names,  # Use captured value
            "monitors": monitors_status,
            "decoder_synced": agg_decoder_synced,
            "decoder_in_message": agg_decoder_in_message,
            "decoder_bytes_decoded": agg_decoder_bytes_decoded,
        }
    
    def add_monitor_for_source(self, source_name: str) -> bool:
        """
        Compatibility method for manual source addition.
        
        Not needed with auto-discovery, but provided for API compatibility.
        The next discovery cycle will pick up the source automatically.
        
        Args:
            source_name: Name of the source to monitor
            
        Returns:
            True (discovery will handle it)
        """
        logger.info(
            f"add_monitor_for_source('{source_name}') called - "
            f"source will be discovered automatically"
        )
        # Trigger immediate discovery
        self._discover_sources()
        return True
    
    def remove_monitor_for_source(self, source_name: str) -> bool:
        """
        Compatibility method for manual source removal.
        
        Not needed with auto-discovery, but provided for API compatibility.
        The next discovery cycle will remove stopped sources automatically.
        
        Args:
            source_name: Name of the source to stop monitoring
            
        Returns:
            True (discovery will handle it)
        """
        logger.info(
            f"remove_monitor_for_source('{source_name}') called - "
            f"source will be removed automatically if stopped"
        )
        # Trigger immediate discovery
        self._discover_sources()
        return True


# Backward compatibility alias
UnifiedEASMonitor = UnifiedEASMonitorService


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_narration_start(post_zczc: np.ndarray, sample_rate: int) -> int:
    """Detect where the attention tone ends and voice narration begins.

    Scans the post-ZCZC ring-buffer audio for sustained energy at the EAS
    (853 Hz + 960 Hz) or EBS (1050 Hz) attention-signal frequencies, then
    returns the sample index of the first narration sample.

    Falls back to a 13-second default when no tone is detected:
        ~4.8 s  three SAME header bursts + inter-burst silences
        ~0.5 s  pause before attention tone
        ~8.5 s  NWS standard attention tone
        ─────
        ~13.3 s before voice narration

    SAME FSK uses 2083 Hz (mark) and 1562 Hz (space) so the detector is
    well clear of header-burst energy.
    """
    FALLBACK_SAMPLES = int(sample_rate * 13)
    MIN_SKIP_SAMPLES = int(sample_rate * 4)   # never skip < 4 s (header bursts)

    if len(post_zczc) < MIN_SKIP_SAMPLES:
        return FALLBACK_SAMPLES

    win_n   = int(sample_rate * 0.25)   # 250 ms FFT window
    hop_n   = win_n // 2                # 50 % overlap → 125 ms hop

    # EAS dual-tone (853 + 960 Hz) and EBS single-tone (1050 Hz)
    TONE_FREQS_HZ = [853.0, 960.0, 1050.0]
    target_bins = [
        int(round(f * win_n / sample_rate))
        for f in TONE_FREQS_HZ
        if 0 < round(f * win_n / sample_rate) < win_n // 2 + 1
    ]

    tone_active: list = []
    for start in range(0, len(post_zczc) - win_n, hop_n):
        chunk = post_zczc[start : start + win_n].astype(np.float64)
        if np.max(np.abs(chunk)) < 1e-6:       # silence window
            tone_active.append(False)
            continue
        mag = np.abs(np.fft.rfft(chunk, n=win_n))
        total = np.sum(mag) + 1e-10
        tone_sum = sum(mag[b] for b in target_bins)
        # Tone present when ≥ 25 % of spectral magnitude sits at target freqs
        tone_active.append((tone_sum / total) >= 0.25)

    if not tone_active:
        return FALLBACK_SAMPLES

    min_win = MIN_SKIP_SAMPLES // hop_n

    # First window (after header region) that has the tone
    tone_start_win = None
    for i in range(min(min_win, len(tone_active)), len(tone_active)):
        if tone_active[i]:
            tone_start_win = i
            break

    if tone_start_win is None:
        # No tone detected — narration follows header bursts directly
        return max(FALLBACK_SAMPLES, MIN_SKIP_SAMPLES)

    # Extend through the tone region; allow up to 3 consecutive silent windows
    # (brief drop-outs from some transmitters)
    silent_run = 0
    tone_end_win = tone_start_win
    for i in range(tone_start_win, len(tone_active)):
        if tone_active[i]:
            tone_end_win = i
            silent_run = 0
        else:
            silent_run += 1
            if silent_run > 3:
                break

    # One extra window of safety margin after tone ends
    narration_start = (tone_end_win + 2) * hop_n
    logger.debug(
        "_find_narration_start: tone span windows %d–%d → narration @ sample %d (%.1f s)",
        tone_start_win, tone_end_win, narration_start, narration_start / sample_rate,
    )
    return max(narration_start, MIN_SKIP_SAMPLES)


def _encode_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    """Encode a float32 numpy array as a 16-bit mono WAV byte string."""
    pcm16 = np.clip(samples, -1.0, 1.0)
    pcm16 = (pcm16 * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)   # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()
