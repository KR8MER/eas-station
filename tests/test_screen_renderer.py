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

import requests

import scripts.screen_renderer as screen_renderer


def _raise_connection_error(*args, **kwargs):  # pragma: no cover - helper
    raise requests.exceptions.ConnectionError("network down")


def test_fetch_data_source_without_preview_samples(monkeypatch):
    renderer = screen_renderer.ScreenRenderer(allow_preview_samples=False)
    monkeypatch.setattr(screen_renderer.requests, "get", _raise_connection_error)

    renderer.fetch_data_source("/api/system_status", "status")

    assert renderer._data_cache["status"] == {}


def test_fetch_data_source_with_preview_samples(monkeypatch):
    renderer = screen_renderer.ScreenRenderer(allow_preview_samples=True)
    monkeypatch.setattr(screen_renderer.requests, "get", _raise_connection_error)

    renderer.fetch_data_source("/api/system_status", "status")

    assert renderer._data_cache["status"] == screen_renderer.PREVIEW_SAMPLE_DATA["status"]
