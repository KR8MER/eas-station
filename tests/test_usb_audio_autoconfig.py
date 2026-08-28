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

Tests for app._detect_external_alsa_card() / _auto_configure_usb_audio_device():
auto-provisioning a USB sound card (e.g. an HS100B DAC) as an audio ingest
source and the local alert-playback output, since every Raspberry Pi's
onboard audio (the vc4hdmi* cards) is output-only and can never be a
capture source.
"""

from __future__ import annotations

import sys

import pytest


class _FakeAlsaAudio:
    """Stand-in for the optional `alsaaudio` extension module."""

    def __init__(self, cards=None, raises=None):
        self._cards = cards or []
        self._raises = raises

    def cards(self):
        if self._raises:
            raise self._raises
        return list(self._cards)


def _install_fake_alsaaudio(monkeypatch, cards=None, raises=None):
    monkeypatch.setitem(sys.modules, "alsaaudio", _FakeAlsaAudio(cards, raises))


# ---------------------------------------------------------------------------
# _detect_external_alsa_card: the card-selection logic, with no DB involved.
# ---------------------------------------------------------------------------

def test_finds_the_sole_external_card(app, monkeypatch):
    from app import _detect_external_alsa_card

    _install_fake_alsaaudio(monkeypatch, ["Device", "vc4hdmi0", "vc4hdmi1"])
    assert _detect_external_alsa_card() == "Device"


def test_onboard_hdmi_only_is_not_external(app, monkeypatch):
    from app import _detect_external_alsa_card

    _install_fake_alsaaudio(monkeypatch, ["vc4hdmi0", "vc4hdmi1"])
    assert _detect_external_alsa_card() is None


def test_no_cards_at_all(app, monkeypatch):
    from app import _detect_external_alsa_card

    _install_fake_alsaaudio(monkeypatch, [])
    assert _detect_external_alsa_card() is None


def test_ambiguous_multiple_external_cards_are_left_alone(app, monkeypatch):
    from app import _detect_external_alsa_card

    _install_fake_alsaaudio(monkeypatch, ["Device", "OtherDac", "vc4hdmi0"])
    assert _detect_external_alsa_card() is None


def test_missing_alsaaudio_module_is_a_silent_no_op(app, monkeypatch):
    from app import _detect_external_alsa_card

    monkeypatch.setitem(sys.modules, "alsaaudio", None)
    assert _detect_external_alsa_card() is None


def test_enumeration_error_is_a_silent_no_op(app, monkeypatch):
    from app import _detect_external_alsa_card

    _install_fake_alsaaudio(monkeypatch, raises=OSError("no /proc/asound"))
    assert _detect_external_alsa_card() is None


# ---------------------------------------------------------------------------
# _auto_configure_usb_audio_device: the DB side, exercised against fakes that
# mimic the AudioSourceConfigDB / EASSettings query surface (query.filter_by
# ().first(), constructor kwargs, db.session.add/commit) without requiring a
# real database -- both models carry Postgres JSONB columns elsewhere in
# their tables that SQLite's dialect cannot create.
# ---------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, result):
        self.result = result
        self.filters = None

    def filter_by(self, **kwargs):
        self.filters = kwargs
        return self

    def first(self):
        return self.result


class _FakeAudioSourceConfigDB:
    created = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        type(self).created = self


class _FakeEASSettingsRow:
    def __init__(self, audio_player="aplay"):
        self.audio_player = audio_player


class _FakeSession:
    def __init__(self):
        self.added = []
        self.committed = False
        self.rolled_back = False

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def remove(self):
        pass

    def close(self):
        pass


@pytest.fixture
def fake_models(monkeypatch):
    import app_core.models as app_models
    from app_core.extensions import db

    _FakeAudioSourceConfigDB.created = None
    _FakeAudioSourceConfigDB.query = _FakeQuery(None)
    session = _FakeSession()

    monkeypatch.setattr(app_models, "AudioSourceConfigDB", _FakeAudioSourceConfigDB)
    monkeypatch.setattr(db, "session", session)

    return _FakeAudioSourceConfigDB, session


def test_creates_source_and_sets_default_output(app, monkeypatch, fake_models):
    from app import _auto_configure_usb_audio_device
    import app_core.models as app_models

    fake_db_cls, session = fake_models
    fake_db_cls.query = _FakeQuery(None)  # no existing alsa source
    eas_settings = _FakeEASSettingsRow(audio_player="aplay")
    monkeypatch.setattr(
        app_models, "EASSettings",
        type("_FakeEASSettings", (), {"query": _FakeQuery(eas_settings)}),
    )

    _install_fake_alsaaudio(monkeypatch, ["Device", "vc4hdmi0"])
    _auto_configure_usb_audio_device()

    assert fake_db_cls.created is not None
    assert fake_db_cls.created.kwargs["source_type"] == "alsa"
    assert fake_db_cls.created.kwargs["config_params"]["device_params"]["device_name"] == (
        "plughw:CARD=Device,DEV=0"
    )
    assert eas_settings.audio_player == "aplay -D plughw:CARD=Device,DEV=0"
    assert session.committed


def test_existing_alsa_source_is_never_duplicated(app, monkeypatch, fake_models):
    from app import _auto_configure_usb_audio_device
    import app_core.models as app_models

    fake_db_cls, session = fake_models
    fake_db_cls.query = _FakeQuery(object())  # an alsa source already exists
    eas_settings = _FakeEASSettingsRow(audio_player="aplay")
    monkeypatch.setattr(
        app_models, "EASSettings",
        type("_FakeEASSettings", (), {"query": _FakeQuery(eas_settings)}),
    )

    _install_fake_alsaaudio(monkeypatch, ["Device", "vc4hdmi0"])
    _auto_configure_usb_audio_device()

    assert fake_db_cls.created is None
    # Output is still wired up independently of the source check.
    assert eas_settings.audio_player == "aplay -D plughw:CARD=Device,DEV=0"


def test_customized_audio_player_is_never_overwritten(app, monkeypatch, fake_models):
    from app import _auto_configure_usb_audio_device
    import app_core.models as app_models

    fake_db_cls, session = fake_models
    fake_db_cls.query = _FakeQuery(None)
    eas_settings = _FakeEASSettingsRow(audio_player="paplay --device=bluez_sink")
    monkeypatch.setattr(
        app_models, "EASSettings",
        type("_FakeEASSettings", (), {"query": _FakeQuery(eas_settings)}),
    )

    _install_fake_alsaaudio(monkeypatch, ["Device", "vc4hdmi0"])
    _auto_configure_usb_audio_device()

    assert eas_settings.audio_player == "paplay --device=bluez_sink"
    # The source is still created even though output was left alone.
    assert fake_db_cls.created is not None


def test_no_external_card_touches_nothing(app, monkeypatch, fake_models):
    from app import _auto_configure_usb_audio_device
    import app_core.models as app_models

    fake_db_cls, session = fake_models
    eas_settings = _FakeEASSettingsRow(audio_player="aplay")
    monkeypatch.setattr(
        app_models, "EASSettings",
        type("_FakeEASSettings", (), {"query": _FakeQuery(eas_settings)}),
    )

    _install_fake_alsaaudio(monkeypatch, ["vc4hdmi0", "vc4hdmi1"])
    _auto_configure_usb_audio_device()

    assert fake_db_cls.created is None
    assert eas_settings.audio_player == "aplay"
    assert not session.committed
