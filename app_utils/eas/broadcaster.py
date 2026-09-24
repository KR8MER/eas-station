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

"""EASBroadcaster: turns a CAP alert into a broadcast WAV, keys the on-air
indicators for its duration, and plays it out."""

import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.system.sd_notify import watchdog_keepalive

from .broadcast_pid import _run_command
from .generator import EASAudioGenerator
from .indicators import (
    BROADCAST_LEAD_IN_SECONDS,
    BROADCAST_LEAD_OUT_SECONDS,
    clear_broadcast_active,
    set_broadcast_active,
    set_incoming_alert,
)
from .same_header_build import build_same_header
from .wav_io import _wav_duration_seconds

# Upper bound on audio generation (SAME + attention + TTS synthesis, which can
# wait on a network TTS provider) before playout starts.  Together with
# max_activation_seconds it bounds the watchdog keepalive around handle_alert.
GENERATION_BUDGET_SECONDS = 120.0


class EASBroadcaster:
    def __init__(
        self,
        db_session,
        model_cls,
        config: Dict[str, object],
        logger,
        location_settings: Optional[Dict[str, object]] = None,
    ) -> None:
        self.db_session = db_session
        self.model_cls = model_cls
        self.config = config
        self.logger = logger
        self.location_settings = location_settings or {}
        self.enabled = bool(config.get('enabled'))
        self.audio_generator = EASAudioGenerator(config, logger, db_session=db_session)

        # GPIO is NOT keyed here.  The eas-station-gpio subprocess owns the
        # physical relay lines (lgpio claims are exclusive per process) and keys
        # them off the Redis broadcast-state marker this broadcaster publishes
        # (set_broadcast_active / set_incoming_alert).  A GPIOController built in
        # this process would only contend for the same lines and fall back to
        # the no-op backend, so we no longer create one.

        if not self.enabled:
            self.logger.info('EAS broadcasting is disabled via configuration.')
        else:
            self.logger.info(
                'EAS broadcasting enabled with output directory %s',
                self.audio_generator.output_dir,
            )

    def _play_audio(self, audio_path: str, eom_wav: Optional[bytes] = None) -> None:
        cmd = self.config.get('audio_player_cmd')
        if not cmd:
            self.logger.debug('No audio player configured; skipping playback.')
            return
        command = list(cmd) + [audio_path]
        self.logger.info('Playing alert audio using %s', ' '.join(command))
        _run_command(command, self.logger, eom_wav=eom_wav)

    def _play_audio_or_bytes(
        self,
        audio_path: Optional[str],
        fallback_bytes: Optional[bytes],
        eom_wav: Optional[bytes] = None,
    ) -> None:
        """Play audio from ``audio_path`` if it exists, otherwise write
        ``fallback_bytes`` to a temporary file and play from there.

        *eom_wav* is the isolated EOM tone-burst for this broadcast (already
        embedded at the end of the composite audio being played here) --
        published alongside the player's PID so a GPIO-triggered
        Dump/Abort can still send a compliant EOM burst per 47 CFR 11.61(a)
        if it kills this process mid-message, before the composite reaches
        its own embedded EOM segment.
        """
        if audio_path and os.path.exists(audio_path):
            self._play_audio(audio_path, eom_wav=eom_wav)
            return
        if fallback_bytes:
            if audio_path:
                self.logger.warning(
                    "Audio file not on disk, playing from memory: %s", audio_path
                )
            fd, tmp_path = tempfile.mkstemp(suffix='.wav')
            try:
                os.write(fd, fallback_bytes)
                os.close(fd)
                self._play_audio(tmp_path, eom_wav=eom_wav)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        elif audio_path:
            self.logger.warning('Audio file not available for playback: %s', audio_path)

    def _get_blockchannel(self, alert: object, payload: Dict[str, object]) -> set:
        """Extract BLOCKCHANNEL values from alert/payload.
        
        BLOCKCHANNEL is a CAP/IPAWS parameter that specifies which distribution
        channels should NOT be used for an alert. Common values include:
        - EAS: Emergency Alert System (broadcast)
        - NWEM: Non-Weather Emergency Message
        - CMAS: Commercial Mobile Alert System (Wireless Emergency Alerts)
        
        The parameter can appear in:
        - payload['raw_json']['properties']['parameters']['BLOCKCHANNEL']
        - payload['parameters']['BLOCKCHANNEL']
        - alert.raw_json['properties']['parameters']['BLOCKCHANNEL']
        
        Returns:
            Set of blocked channel names (uppercase), empty set if none blocked
        """
        blocked: set = set()
        
        def _extract_from_parameters(params: dict) -> None:
            if not isinstance(params, dict):
                return
            # Check uppercase first, then lowercase - use explicit None check to avoid
            # issues with empty lists being falsy
            blockchannel = params.get('BLOCKCHANNEL')
            if blockchannel is None:
                blockchannel = params.get('blockchannel', [])
            if isinstance(blockchannel, str):
                blocked.add(blockchannel.strip().upper())
            elif isinstance(blockchannel, (list, tuple)):
                for item in blockchannel:
                    if item:
                        blocked.add(str(item).strip().upper())
        
        # Check payload['parameters']
        if isinstance(payload.get('parameters'), dict):
            _extract_from_parameters(payload['parameters'])
        
        # Check payload['raw_json']['properties']['parameters']
        raw_json = payload.get('raw_json', {})
        if isinstance(raw_json, dict):
            props = raw_json.get('properties', {})
            if isinstance(props, dict):
                _extract_from_parameters(props.get('parameters', {}))
        
        # Check alert.raw_json['properties']['parameters']
        alert_raw_json = getattr(alert, 'raw_json', None)
        if isinstance(alert_raw_json, dict):
            props = alert_raw_json.get('properties', {})
            if isinstance(props, dict):
                _extract_from_parameters(props.get('parameters', {}))
        
        return blocked

    def handle_alert(self, alert: object, payload: Dict[str, object]) -> Dict[str, object]:
        # Generation plus playout blocks the caller for the whole broadcast --
        # 165 s of audio + ~18 s of generation already exceeds the poller's
        # 180 s WatchdogSec.  Without a keepalive systemd killed the poller
        # mid-playout, before eas_forwarded was recorded, and the restart's
        # catch-up sweep aired the alert again: 19 times in one hour on
        # 2026-09-24.  The keepalive is bounded, so a genuine hang is still
        # caught.
        max_activation = float(self.config.get('max_activation_seconds', 300) or 300)
        budget = (
            GENERATION_BUDGET_SECONDS + BROADCAST_LEAD_IN_SECONDS
            + max_activation + BROADCAST_LEAD_OUT_SECONDS
        )
        with watchdog_keepalive(budget):
            return self._handle_alert(alert, payload)

    def _handle_alert(self, alert: object, payload: Dict[str, object]) -> Dict[str, object]:
        result: Dict[str, object] = {"same_triggered": False}
        if not self.enabled or not alert:
            result["reason"] = "Broadcasting disabled"
            return result

        status = (getattr(alert, 'status', '') or '').lower()
        message_type = (payload.get('message_type') or getattr(alert, 'message_type', '') or '').lower()
        event_name = (getattr(alert, 'event', '') or payload.get('event') or '').strip().lower()

        suppressed_events = {
            'special weather statement',
            'dense fog advisory',
        }

        # Note: BLOCKCHANNEL in IPAWS/CAP applies to automated IPAWS distribution
        # systems, not to local EAS stations monitoring the NWS API directly.
        # Local EAS stations must make their own broadcast decisions based on
        # event type and geographic coverage, not the BLOCKCHANNEL parameter.

        if status not in {'actual', 'test'}:
            self.logger.debug('Skipping EAS generation for status %s', status)
            result['reason'] = f"Unsupported status: {status}"
            return result
        if message_type not in {'alert', 'update', 'test'}:
            self.logger.debug('Skipping EAS generation for message type %s', message_type)
            result['reason'] = f"Unsupported message type: {message_type}"
            return result
        if event_name in suppressed_events:
            pretty_event = getattr(alert, 'event', '') or payload.get('event') or event_name
            self.logger.info('Skipping EAS generation for event %s', pretty_event)
            result['reason'] = f"Suppressed event {pretty_event}"
            return result

        try:
            header, location_codes, event_code = build_same_header(
                alert,
                payload,
                self.config,
                self.location_settings,
            )
        except ValueError as exc:
            self.logger.info('Skipping EAS generation: %s', exc)
            result['reason'] = str(exc)
            return result

        try:
            (
                audio_filename,
                text_filename,
                message_text,
                audio_bytes,
                text_payload,
                segment_payload,
            ) = self.audio_generator.build_files(alert, payload, header, location_codes)
        except Exception as exc:
            self.logger.error('Audio generation failed for alert %s: %s',
                              getattr(alert, 'identifier', 'unknown'), exc)
            result['reason'] = f"Audio generation failed: {exc}"
            return result

        # EOM is now embedded in audio_bytes (built inside build_files()).
        # Extract the EOM segment for separate database storage so it can be
        # displayed/downloaded individually from the audio detail page.
        eom_bytes = (segment_payload.get('eom') or {}).get('wav_bytes')

        audio_path = os.path.join(self.audio_generator.output_dir, audio_filename)

        # Populate result fields that are known at this point, but defer
        # setting same_triggered=True until the database commit succeeds so
        # callers never see a "triggered" status when the record was not saved
        # and audio was never played.
        result.update(
            {
                "event_code": event_code,
                "same_header": header,
                "audio_path": audio_path,
                "location_codes": location_codes,
            }
        )

        alert_identifier = getattr(alert, 'identifier', None) or payload.get('identifier')
        forwarding_decision = str(payload.get('forwarding_decision', '') or '').lower()
        is_forwarded = forwarding_decision == 'forwarded' or bool(payload.get('forwarded', False))

        # Signal hardware indicators that an alert has arrived but broadcast has
        # not started yet.  The eas-station-gpio subprocess reads this marker and
        # pulses any INCOMING_ALERT pins / shows the pre-broadcast tower light.
        set_incoming_alert(
            event_code=event_code or '',
            identifier=str(alert_identifier) if alert_identifier else '',
        )

        # Create and persist database record BEFORE queue/immediate mode split
        # This ensures both modes have consistent database tracking
        segment_metadata = {
            key: {
                'duration_seconds': value.get('duration_seconds'),
                'size_bytes': value.get('size_bytes'),
            }
            for key, value in segment_payload.items()
            if value
        }

        record = self.model_cls(
            cap_alert_id=getattr(alert, 'id', None),
            same_header=header,
            audio_filename=audio_filename,
            text_filename=text_filename,
            audio_data=audio_bytes,
            eom_audio_data=eom_bytes,
            same_audio_data=(segment_payload.get('same') or {}).get('wav_bytes'),
            attention_audio_data=(segment_payload.get('attention') or {}).get('wav_bytes'),
            tts_audio_data=(segment_payload.get('tts') or {}).get('wav_bytes'),
            buffer_audio_data=(segment_payload.get('buffer') or {}).get('wav_bytes'),
            tts_warning=text_payload.get('tts_warning'),
            tts_provider=text_payload.get('voiceover_provider'),
            text_payload=text_payload,
            created_at=datetime.now(timezone.utc),
            metadata_payload={
                'event': getattr(alert, 'event', ''),
                'event_code': event_code,
                'severity': getattr(alert, 'severity', ''),
                'status': getattr(alert, 'status', ''),
                'message_type': getattr(alert, 'message_type', ''),
                'locations': location_codes,
                'segments': segment_metadata,
                'has_tts': bool(segment_payload.get('tts')),
                'has_eom': bool(segment_payload.get('eom')),
            },
        )

        try:
            self.db_session.add(record)
            self.db_session.commit()
            self.logger.info('Stored EAS message metadata for alert %s', getattr(alert, 'identifier', 'unknown'))
            result['record_id'] = getattr(record, 'id', None)
            # Only mark as triggered after the record is safely persisted.
            # If the commit fails the caller will see same_triggered=False and
            # an 'error' key rather than a false-positive success status.
            result['same_triggered'] = True
        except Exception as exc:
            self.logger.error(f"Failed to persist EAS message record: {exc}")
            self.db_session.rollback()
            result['error'] = str(exc)
            # If database persistence fails, we can't continue
            return result

        # Publish broadcast state to Redis *before* playout begins.  This both
        # drives the browser countdown overlay and is the rising edge the
        # eas-station-gpio subprocess watches to key the relay (transmitter PTT
        # / audio mute / duration-of-alert holds + flash) — so the relay is
        # asserted for the whole broadcast without this process touching GPIO.
        _duration_hint = _wav_duration_seconds(audio_bytes) if audio_bytes else 0.0
        _event_info = EVENT_CODE_REGISTRY.get(event_code or '', {})
        _event_label = (
            _event_info.get('name', event_code) if isinstance(_event_info, dict) else event_code
        ) or 'EAS Alert'
        # Prefer the alert's own headline when available -- it's usually
        # more specific than the generic event-type name ("Severe
        # Thunderstorm Warning issued until 7:15 PM for Delaware County"
        # vs. just "Severe Thunderstorm Warning") -- this is also what
        # every connected page's countdown overlay and every Icecast
        # stream's "now playing" title show for the duration of the
        # broadcast (see _reconcile_broadcast_metadata() in
        # eas_monitoring_service.py), so the more specific text is worth
        # preferring here same as it always was for this one path.
        _alert_headline = (getattr(alert, 'headline', '') or '').strip()
        if _alert_headline:
            _event_label = _alert_headline
        _bcast_source = 'forwarded' if is_forwarded else 'auto'
        # Phase breakpoints for the countdown overlay -- see
        # set_broadcast_active()'s docstring. This path has no chime
        # support, so these are just the header/EOM burst durations.
        _same_bytes = (segment_payload.get('same') or {}).get('wav_bytes')
        _header_seconds = _wav_duration_seconds(_same_bytes) if _same_bytes else 0.0
        _eom_seconds = _wav_duration_seconds(eom_bytes) if eom_bytes else 0.0
        set_broadcast_active(
            event_code=event_code or '',
            label=_event_label,
            duration_seconds=BROADCAST_LEAD_IN_SECONDS + _duration_hint + BROADCAST_LEAD_OUT_SECONDS,
            source=_bcast_source,
            identifier=str(alert_identifier) if alert_identifier else '',
            header_seconds=_header_seconds + BROADCAST_LEAD_IN_SECONDS,
            eom_seconds=_eom_seconds + BROADCAST_LEAD_IN_SECONDS,
        )
        # Relay lead-in: the marker above already fired the rising edge the
        # GPIO subprocess keys off of, so the relay is asserting now -- this
        # sleep is what actually gives the transmitter this long to
        # stabilize before real audio starts. See BROADCAST_LEAD_IN_SECONDS.
        time.sleep(BROADCAST_LEAD_IN_SECONDS)

        playout_start = time.monotonic()
        try:
            # Inject into Icecast FIRST so stream listeners hear the alert
            # in sync with local playback.  inject_eas_audio() queues all
            # audio chunks into the BroadcastQueue immediately (no blocking),
            # then _play_audio_or_bytes() plays locally while the
            # IcecastStreamer drains those chunks to FFmpeg in real time.
            # Previously injection happened AFTER _play_audio_or_bytes()
            # returned, meaning Icecast listeners missed the entire alert.
            _injection_attempted = False
            _injected_ok = False
            try:
                from app_core.audio.eas_stream_injector import inject_eas_audio, has_controller
                _wav_data = audio_bytes
                if _wav_data is None and audio_path and os.path.exists(audio_path):
                    with open(audio_path, 'rb') as _f:
                        _wav_data = _f.read()
                if _wav_data:
                    _injection_attempted = True
                    if has_controller():
                        _injected_ok = bool(inject_eas_audio(_wav_data))
                    else:
                        # This process has no AudioIngestController of its
                        # own -- eas_stream_injector's module-level
                        # _controller is only registered inside
                        # eas-station-audio.service (eas_monitoring_service.py
                        # calls set_controller() once at startup). A direct
                        # inject_eas_audio() call here silently no-ops: it
                        # returns False and logs at debug level, so every
                        # CAP/IPAWS auto-forward (cap_poller.py -- the main
                        # ingest path, the gated-alert auto-release timer,
                        # and the forwarding catch-up sweep, all running as
                        # eas-station-poller.service) and every operator
                        # "Approve" on a held/gated alert (pending_alerts.py,
                        # running as eas-station-web.service) recorded a
                        # broadcast in the database and logged "Auto-
                        # forwarded ... to air chain" while no audio ever
                        # reached Icecast or local playback. Ask the audio
                        # service -- the process that owns the controller and
                        # the running IcecastStreamer threads -- to do the
                        # injection instead, over the same Redis command
                        # channel the Manual Send path already uses for this
                        # exact reason (AudioCommandPublisher.inject_raw_eas_audio,
                        # webapp/eas/workflow.py).
                        from app_core.audio.redis_commands import get_audio_command_publisher
                        _inj_resp = get_audio_command_publisher().inject_raw_eas_audio(_wav_data)
                        _injected_ok = bool(_inj_resp.get('success'))
                        if not _injected_ok:
                            self.logger.error(
                                "EAS stream injection via Redis failed -- alert audio "
                                "was NOT delivered to Icecast: %s",
                                _inj_resp.get('message', 'unknown error'),
                            )
            except Exception as _inj_exc:
                self.logger.warning("EAS stream injection failed (non-fatal): %s", _inj_exc)

            # Record the outcome on the already-committed row so a transient
            # failure (audio-service down, Redis unreachable at exactly this
            # moment) is a fact cap_poller.py's retry_failed_icecast_injections()
            # sweep can find and re-send -- via the same resend command the
            # EASMessage detail page's manual "Resend" button uses -- instead
            # of a broadcast being permanently logged as "forwarded" while no
            # listener ever heard it.  Not written when nothing was ever
            # attempted (no audio bytes at all): that is a different,
            # unrelated failure already surfaced via the "reason" result key.
            if _injection_attempted:
                try:
                    _meta = dict(record.metadata_payload or {})
                    _meta['icecast_injected'] = _injected_ok
                    record.metadata_payload = _meta
                    self.db_session.add(record)
                    self.db_session.commit()
                except Exception as _meta_exc:
                    self.logger.debug(
                        "Could not persist Icecast injection outcome metadata "
                        "for EASMessage id=%s: %s", getattr(record, 'id', None), _meta_exc,
                    )
                    try:
                        self.db_session.rollback()
                    except Exception:
                        pass

            # audio_bytes contains the complete broadcast sequence:
            # SAME header (3x) → attention tone → TTS narration → EOM.
            # All segments are in a single uninterrupted audio file, so no
            # gap can appear between the narration and the EOM burst.
            self._play_audio_or_bytes(audio_path, audio_bytes, eom_wav=eom_bytes)

            # Hold the broadcast marker for the full composite duration even if
            # playback returned early.  The marker's rising and falling edges are
            # what the eas-station-gpio subprocess keys and releases the relay
            # on, and it samples them at 1 Hz — so a marker that is set and
            # cleared within the same millisecond is never observed at all and
            # the transmitter is never keyed.  That is exactly what happens on
            # any station without a local EAS_AUDIO_PLAYER (Icecast-only or
            # external-ENDEC installs): _play_audio_or_bytes() logs "no audio
            # player configured" and returns immediately, while the encoder is
            # still working through the queued SAME burst.  The manual send path
            # (webapp/eas/workflow.py) and the RWT scheduler already hold the
            # marker this way; auto-forwarded alerts — every OTA relay and CAP
            # auto-forward — came through here and did not.
            hold_seconds = min(
                float(_duration_hint or 0.0),
                float(self.config.get('max_activation_seconds', 300) or 300),
            )
            remaining_playout = hold_seconds - (time.monotonic() - playout_start)
            if remaining_playout > 0:
                time.sleep(remaining_playout)
        finally:
            # Relay lead-out: hold the relay this much longer past the actual
            # end of playout before releasing it. See BROADCAST_LEAD_OUT_SECONDS.
            time.sleep(BROADCAST_LEAD_OUT_SECONDS)
            # Falling edge: the GPIO subprocess releases the relay when this
            # marker clears (and self-releases on the marker TTL as a backstop).
            # Pass the identifier so an overlapping newer broadcast's marker is
            # never erased by this one finishing.
            clear_broadcast_active(
                identifier=str(alert_identifier) if alert_identifier else ''
            )

        return result
