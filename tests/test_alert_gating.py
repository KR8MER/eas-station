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

"""Tests for the gated-alerts hold-off timer (auto_forward.py gate hooks).

Covers:
  - Immediate urgency / Extreme severity always bypass the gate.
  - A held (gated) alert returns forwarded=False with a non-null reason
    (critical: retry_unevaluated_forwards() in cap_poller.py only re-fires
    alerts whose eas_forwarding_reason IS NULL -- a null reason here would
    cause the sweep to re-run the whole gate chain, and re-create a pending
    row, every retry cycle).
  - Gating disabled leaves behavior unchanged.
  - _resolve_gate is idempotent: a pre-existing pending row is reused, not
    duplicated, and _resolve_gate always queries via the passed db_session
    (not the Flask-SQLAlchemy Model.query shortcut, which would raise
    outside an app context -- the CAP poller calls this with a plain
    SQLAlchemy Session, no Flask app).
  - A cancelled row blocks forever; an approved/released row falls through
    to the normal broadcast tail unchanged.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_auto_forward_module():
    """Load app_core/audio/auto_forward.py directly from disk, isolated from
    the full app_core.audio package (SDR/ALSA pipeline). Mirrors the harness
    in tests/test_ecig_compliance.py."""
    import importlib.util
    import contextlib

    sys.modules.setdefault('app_utils.vtec', MagicMock(
        VTEC_BROADCAST_ACTIONS=set(),
        VTEC_SKIP_ACTIONS=set(),
        VTEC_TERMINAL_ACTIONS=set(),
    ))

    @contextlib.contextmanager
    def _noop_ctx(*args, **kwargs):
        yield None

    logging_ctx_stub = MagicMock()
    logging_ctx_stub.push_alert = MagicMock(return_value=object())
    logging_ctx_stub.pop_alert = MagicMock()
    sys.modules.setdefault('app_core.logging_context', logging_ctx_stub)
    sys.modules.setdefault('app_core.extensions', MagicMock())
    sys.modules.setdefault('app_core.redis_client', MagicMock())
    sys.modules.setdefault('app_utils.event_codes', MagicMock(
        EVENT_CODE_REGISTRY={
            'CEM': {'name': 'Civil Emergency Message', 'severity': 'Unknown', 'urgency': 'Unknown'},
            'RWT': {'name': 'Required Weekly Test', 'severity': 'Unknown', 'urgency': 'Unknown'},
            'TOR': {'name': 'Tornado Warning', 'severity': 'Extreme', 'urgency': 'Immediate'},
            'SVR': {'name': 'Severe Thunderstorm Warning', 'severity': 'Moderate', 'urgency': 'Expected'},
        },
    ))

    path = ROOT / 'app_core' / 'audio' / 'auto_forward.py'
    spec = importlib.util.spec_from_file_location('auto_forward_gating_under_test', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cap_alert(*, severity='Moderate', urgency='Expected', alert_id=7, event='Severe Thunderstorm Warning'):
    from datetime import datetime, timezone, timedelta
    sent = datetime.now(timezone.utc) - timedelta(minutes=1)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    return SimpleNamespace(
        id=alert_id,
        identifier='TEST-GATE-001',
        status='Actual',
        scope='Public',
        message_type='Alert',
        sent=sent,
        expires=expires,
        source='IPAWS',
        event=event,
        severity=severity,
        urgency=urgency,
        headline=event,
        vtec_action=None,
    )


class TestBypassCheck(unittest.TestCase):
    """_bypasses_gate: Immediate urgency or Extreme severity always bypass."""

    @classmethod
    def setUpClass(cls):
        cls._mod = _load_auto_forward_module()

    def test_extreme_severity_bypasses(self):
        self.assertTrue(self._mod._bypasses_gate('Extreme', 'Expected'))

    def test_immediate_urgency_bypasses(self):
        self.assertTrue(self._mod._bypasses_gate('Minor', 'Immediate'))

    def test_case_insensitive(self):
        self.assertTrue(self._mod._bypasses_gate('extreme', 'expected'))
        self.assertTrue(self._mod._bypasses_gate('minor', 'immediate'))

    def test_moderate_expected_does_not_bypass(self):
        self.assertFalse(self._mod._bypasses_gate('Moderate', 'Expected'))

    def test_none_values_do_not_bypass(self):
        self.assertFalse(self._mod._bypasses_gate(None, None))


class TestResolveGateUnit(unittest.TestCase):
    """Direct unit tests of _resolve_gate's create/reuse/session-usage contract."""

    @classmethod
    def setUpClass(cls):
        cls._mod = _load_auto_forward_module()

    def _fake_models(self, existing_row=None, settings_enabled=True, hold_off_seconds=120):
        gated_alert_cls = MagicMock(name='GatedAlert')
        query_mock = MagicMock()
        query_mock.filter_by.return_value.first.return_value = existing_row
        gated_alert_cls.query = query_mock  # must NOT be used by _resolve_gate

        settings_cls = MagicMock(name='AlertGatingSettings')

        fake_models_module = MagicMock()
        fake_models_module.GatedAlert = gated_alert_cls
        fake_models_module.AlertGatingSettings = settings_cls

        db_session = MagicMock()
        db_session.get.return_value = SimpleNamespace(enabled=settings_enabled, hold_off_seconds=hold_off_seconds)
        # db_session.query(GatedAlert) is the *only* correct way to look up
        # an existing row -- assert this explicitly below.
        db_session.query.return_value.filter_by.return_value.first.return_value = existing_row

        return gated_alert_cls, fake_models_module, db_session

    def test_uses_db_session_query_not_model_query(self):
        """Regression test: _resolve_gate must never call GatedAlert.query
        (a Flask-SQLAlchemy shortcut requiring app context) -- it must go
        through the passed db_session, since the CAP poller calls this with
        a plain SQLAlchemy Session and no Flask app context at all."""
        gated_alert_cls, fake_models_module, db_session = self._fake_models(existing_row=None)
        with patch.dict(sys.modules, {'app_core.models': fake_models_module}):
            action, row = self._mod._resolve_gate(
                db_session, source='cap',
                lookup_kwargs={'source': 'cap', 'cap_alert_id': 7},
                defaults={'cap_alert_id': 7, 'identifier': 'TEST-GATE-001'},
            )
        db_session.query.assert_any_call(gated_alert_cls)
        gated_alert_cls.query.filter_by.assert_not_called()
        self.assertEqual(action, 'hold')

    def test_creates_pending_row_when_none_exists_and_gating_enabled(self):
        gated_alert_cls, fake_models_module, db_session = self._fake_models(existing_row=None, settings_enabled=True)
        with patch.dict(sys.modules, {'app_core.models': fake_models_module}):
            action, row = self._mod._resolve_gate(
                db_session, source='cap',
                lookup_kwargs={'source': 'cap', 'cap_alert_id': 7},
                defaults={'cap_alert_id': 7, 'identifier': 'TEST-GATE-001'},
            )
        self.assertEqual(action, 'hold')
        gated_alert_cls.assert_called_once()
        db_session.add.assert_called_once()
        db_session.commit.assert_called_once()

    def test_gating_disabled_returns_proceed_without_creating_row(self):
        gated_alert_cls, fake_models_module, db_session = self._fake_models(existing_row=None, settings_enabled=False)
        with patch.dict(sys.modules, {'app_core.models': fake_models_module}):
            action, row = self._mod._resolve_gate(
                db_session, source='cap',
                lookup_kwargs={'source': 'cap', 'cap_alert_id': 7},
                defaults={'cap_alert_id': 7, 'identifier': 'TEST-GATE-001'},
            )
        self.assertEqual(action, 'proceed')
        self.assertIsNone(row)
        gated_alert_cls.assert_not_called()

    def test_pending_row_reused_not_duplicated(self):
        existing = SimpleNamespace(id=1, status='pending', hold_until=None)
        gated_alert_cls, fake_models_module, db_session = self._fake_models(existing_row=existing)
        with patch.dict(sys.modules, {'app_core.models': fake_models_module}):
            action, row = self._mod._resolve_gate(
                db_session, source='cap',
                lookup_kwargs={'source': 'cap', 'cap_alert_id': 7},
                defaults={'cap_alert_id': 7, 'identifier': 'TEST-GATE-001'},
            )
        self.assertEqual(action, 'hold')
        self.assertIs(row, existing)
        gated_alert_cls.assert_not_called()  # no second row created
        db_session.add.assert_not_called()

    def test_cancelled_row_blocks(self):
        existing = SimpleNamespace(id=1, status='cancelled', hold_until=None)
        gated_alert_cls, fake_models_module, db_session = self._fake_models(existing_row=existing)
        with patch.dict(sys.modules, {'app_core.models': fake_models_module}):
            action, row = self._mod._resolve_gate(
                db_session, source='cap',
                lookup_kwargs={'source': 'cap', 'cap_alert_id': 7},
                defaults={'cap_alert_id': 7, 'identifier': 'TEST-GATE-001'},
            )
        self.assertEqual(action, 'blocked')

    def test_approved_row_proceeds(self):
        existing = SimpleNamespace(id=1, status='approved', hold_until=None)
        gated_alert_cls, fake_models_module, db_session = self._fake_models(existing_row=existing)
        with patch.dict(sys.modules, {'app_core.models': fake_models_module}):
            action, row = self._mod._resolve_gate(
                db_session, source='cap',
                lookup_kwargs={'source': 'cap', 'cap_alert_id': 7},
                defaults={'cap_alert_id': 7, 'identifier': 'TEST-GATE-001'},
            )
        self.assertEqual(action, 'proceed')

    def test_released_row_proceeds(self):
        existing = SimpleNamespace(id=1, status='released', hold_until=None)
        gated_alert_cls, fake_models_module, db_session = self._fake_models(existing_row=existing)
        with patch.dict(sys.modules, {'app_core.models': fake_models_module}):
            action, row = self._mod._resolve_gate(
                db_session, source='cap',
                lookup_kwargs={'source': 'cap', 'cap_alert_id': 7},
                defaults={'cap_alert_id': 7, 'identifier': 'TEST-GATE-001'},
            )
        self.assertEqual(action, 'proceed')


class TestCapAlertGateIntegration(unittest.TestCase):
    """End-to-end through auto_forward_cap_alert() with _resolve_gate patched,
    verifying the hook's own reason-string / early-return / status-update
    behavior (not _resolve_gate's internals, covered above)."""

    @classmethod
    def setUpClass(cls):
        cls._mod = _load_auto_forward_module()

    def _call(self, cap_alert, resolve_gate_return):
        with patch.object(self._mod, '_resolve_gate', return_value=resolve_gate_return) as mock_resolve, \
             patch.object(self._mod, '_update_cap_forwarding_status') as mock_update, \
             patch.object(self._mod, '_acquire_dedupe_lock'), \
             patch.object(self._mod, 'is_duplicate_broadcast', return_value=True):
            result = self._mod.auto_forward_cap_alert(
                cap_alert,
                {'raw_json': {'properties': {'geocode': {'SAME': ['039001']}}}},
                db_session=MagicMock(),
                eas_message_cls=MagicMock(),
                eas_config={'enabled': True, 'forwarded_event_codes': []},
            )
        return result, mock_resolve, mock_update

    def test_extreme_severity_never_calls_resolve_gate(self):
        cap_alert = _cap_alert(severity='Extreme', urgency='Expected')
        result, mock_resolve, mock_update = self._call(cap_alert, ('hold', SimpleNamespace(id=1, hold_until=None)))
        mock_resolve.assert_not_called()
        # Falls through to dedup, which is forced to report a duplicate --
        # proves the gate did not intercept it.
        self.assertIn('duplicate', (result.get('reason') or '').lower())

    def test_immediate_urgency_never_calls_resolve_gate(self):
        cap_alert = _cap_alert(severity='Minor', urgency='Immediate')
        result, mock_resolve, mock_update = self._call(cap_alert, ('hold', SimpleNamespace(id=1, hold_until=None)))
        mock_resolve.assert_not_called()
        self.assertIn('duplicate', (result.get('reason') or '').lower())

    def test_held_alert_returns_non_null_reason_and_updates_status(self):
        from datetime import datetime, timezone
        gate_row = SimpleNamespace(id=42, hold_until=datetime.now(timezone.utc))
        cap_alert = _cap_alert(severity='Moderate', urgency='Expected')
        result, mock_resolve, mock_update = self._call(cap_alert, ('hold', gate_row))

        mock_resolve.assert_called_once()
        self.assertFalse(result['forwarded'])
        self.assertIn('Pending', result.get('reason') or '')
        self.assertEqual(result.get('pending_alert_id'), 42)

        # Critical regression check: the reason passed to
        # _update_cap_forwarding_status must be non-null, or
        # retry_unevaluated_forwards() will re-run this alert every sweep.
        mock_update.assert_called_once()
        call_args = mock_update.call_args[0]
        forwarded_arg, reason_arg = call_args[2], call_args[3]
        self.assertFalse(forwarded_arg)
        self.assertTrue(reason_arg)
        self.assertIn('Pending', reason_arg)

    def test_blocked_alert_returns_cancelled_reason(self):
        cap_alert = _cap_alert(severity='Moderate', urgency='Expected')
        result, mock_resolve, mock_update = self._call(
            cap_alert, ('blocked', SimpleNamespace(id=1, status='cancelled')),
        )
        self.assertFalse(result['forwarded'])
        self.assertIn('Cancelled', result.get('reason') or '')
        mock_update.assert_called_once()
        call_args = mock_update.call_args[0]
        self.assertTrue(call_args[3])  # non-null reason here too

    def test_proceed_falls_through_to_dedup(self):
        cap_alert = _cap_alert(severity='Moderate', urgency='Expected')
        result, mock_resolve, mock_update = self._call(
            cap_alert, ('proceed', SimpleNamespace(id=1, status='approved')),
        )
        mock_resolve.assert_called_once()
        # Forced-duplicate dedup fired, proving the gate stepped aside.
        self.assertIn('duplicate', (result.get('reason') or '').lower())

    def test_gating_disabled_falls_through(self):
        cap_alert = _cap_alert(severity='Moderate', urgency='Expected')
        result, mock_resolve, mock_update = self._call(cap_alert, ('proceed', None))
        mock_resolve.assert_called_once()
        self.assertIn('duplicate', (result.get('reason') or '').lower())


class TestOtaAlertGateIntegration(unittest.TestCase):
    """End-to-end through auto_forward_ota_alert() with _resolve_gate patched."""

    @classmethod
    def setUpClass(cls):
        cls._mod = _load_auto_forward_module()

    def _alert_dict(self, event_code='SVR'):
        return {
            'event_code': event_code,
            'location_codes': ['039001'],
            'source_name': 'test-source',
            'identifier': 'OTA-TEST-001',
        }

    def _call(self, alert_dict, resolve_gate_return, is_duplicate=False):
        # Note: unlike the CAP path, OTA's cross-source dedup check runs
        # BEFORE the gate hook (dedup needs no alert_object; the gate hook
        # is inserted right after alert_object is built). So "not a
        # duplicate" must be the default here to let execution reach the
        # gate hook at all -- the CAP tests use the opposite trick because
        # CAP's gate hook runs before its dedup check.
        db_session = MagicMock()
        db_session.query.return_value.filter.return_value.all.return_value = []
        with patch.object(self._mod, '_resolve_gate', return_value=resolve_gate_return) as mock_resolve, \
             patch.object(self._mod, '_acquire_dedupe_lock'), \
             patch.object(self._mod, 'is_duplicate_broadcast', return_value=is_duplicate):
            result = self._mod.auto_forward_ota_alert(
                alert_dict=alert_dict,
                db_session=db_session,
                eas_message_cls=MagicMock(),
                eas_config={'enabled': True, 'forwarded_event_codes': []},
            )
        return result, mock_resolve

    def test_extreme_event_code_never_calls_resolve_gate(self):
        # TOR resolves to severity=Extreme in the stubbed EVENT_CODE_REGISTRY.
        # Dedup forced True here since a bypassed alert should never even
        # reach the gate hook, regardless of dedup outcome.
        result, mock_resolve = self._call(
            self._alert_dict(event_code='TOR'), ('hold', SimpleNamespace(id=1, hold_until=None)), is_duplicate=True,
        )
        mock_resolve.assert_not_called()
        self.assertIn('duplicate', (result.get('reason') or '').lower())

    def test_held_alert_returns_pending_reason(self):
        from datetime import datetime, timezone
        gate_row = SimpleNamespace(id=99, hold_until=datetime.now(timezone.utc))
        result, mock_resolve = self._call(self._alert_dict(event_code='SVR'), ('hold', gate_row))
        mock_resolve.assert_called_once()
        self.assertFalse(result['forwarded'])
        self.assertIn('Pending', result.get('reason') or '')
        self.assertEqual(result.get('pending_alert_id'), 99)

    def test_blocked_alert_returns_cancelled_reason(self):
        result, mock_resolve = self._call(
            self._alert_dict(event_code='SVR'), ('blocked', SimpleNamespace(id=1, status='cancelled')),
        )
        self.assertFalse(result['forwarded'])
        self.assertIn('Cancelled', result.get('reason') or '')

    def test_proceed_reaches_broadcaster(self):
        with patch('app_utils.eas.EASBroadcaster') as MockBroadcaster:
            mock_instance = MockBroadcaster.return_value
            mock_instance.handle_alert.return_value = {'same_triggered': False, 'reason': 'test stub'}
            result, mock_resolve = self._call(
                self._alert_dict(event_code='SVR'), ('proceed', SimpleNamespace(id=1, status='approved')),
            )
        mock_resolve.assert_called_once()
        # Reaching EASBroadcaster construction proves the gate stepped aside.
        mock_instance.handle_alert.assert_called_once()


if __name__ == '__main__':
    unittest.main()
