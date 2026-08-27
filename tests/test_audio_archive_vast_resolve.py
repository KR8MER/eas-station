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

"""Regression test for VAST XML namespace handling in resolve_stream_url().

Real-world VAST responses (VAST 3.0+, which is the norm -- iHeartRadio's ad
server included) declare a default XML namespace on the root element, e.g.
``<VAST xmlns="http://www.iab.com/VAST">``. ElementTree folds that into
every descendant's parsed tag -- ``<MediaFile>`` becomes
``{http://www.iab.com/VAST}MediaFile`` -- so a bare ``root.iter("MediaFile")``
silently matches nothing. Before this fix, clicking "resolve and play" on
any ad in the Audio Archives Song History page did nothing useful: the
request always came back "VAST parsed but no audio MediaFile found", even
for VAST payloads that had a perfectly playable audio/mpeg MediaFile.
"""

import pytest
from unittest.mock import Mock, patch

pytestmark = pytest.mark.unit

_NAMESPACED_VAST = b"""<VAST version="4.3" xmlns="http://www.iab.com/VAST">
  <Ad id="1">
    <InLine>
      <AdSystem version="1.0">TritonCreativeManager</AdSystem>
      <AdTitle>Back to School Sale</AdTitle>
      <Creatives>
        <Creative>
          <Linear>
            <Duration>00:00:30.000</Duration>
            <MediaFiles>
              <MediaFile delivery="progressive" type="audio/mpeg" bitrate="192">
                <![CDATA[https://cdn.example.com/ads/back-to-school.mp3]]>
              </MediaFile>
            </MediaFiles>
          </Linear>
        </Creative>
      </Creatives>
    </InLine>
  </Ad>
</VAST>"""

_UNNAMESPACED_VAST = b"""<VAST version="3.0">
  <Ad id="1">
    <InLine>
      <AdSystem version="1.0">LegacyAdServer</AdSystem>
      <AdTitle>Legacy Ad</AdTitle>
      <Creatives>
        <Creative>
          <Linear>
            <Duration>00:00:15.000</Duration>
            <MediaFiles>
              <MediaFile delivery="progressive" type="audio/mpeg" bitrate="128">
                <![CDATA[https://cdn.example.com/ads/legacy.mp3]]>
              </MediaFile>
            </MediaFiles>
          </Linear>
        </Creative>
      </Creatives>
    </InLine>
  </Ad>
</VAST>"""


def _mock_response(content_type: str, body: bytes):
    resp = Mock()
    resp.headers = {"Content-Type": content_type}
    resp.read = Mock(return_value=body)
    resp.__enter__ = Mock(return_value=resp)
    resp.__exit__ = Mock(return_value=False)
    return resp


def test_resolve_finds_media_file_in_namespaced_vast():
    """The bug: xmlns="..." on <VAST> broke the bare root.iter("MediaFile") lookup."""
    from webapp.audio_archive.metadata import resolve_stream_url

    with patch("webapp.audio_archive.metadata._is_public_url", return_value=True), \
         patch("webapp.audio_archive.metadata.urllib.request.urlopen",
               return_value=_mock_response("application/xml", _NAMESPACED_VAST)):
        result = resolve_stream_url("https://example.com/vast/123")

    assert result["type"] == "vast"
    assert result["audio_url"] == "https://cdn.example.com/ads/back-to-school.mp3"
    assert result["mime"] == "audio/mpeg"
    assert result["ad_title"] == "Back to School Sale"
    assert result["ad_system"] == "TritonCreativeManager"
    assert result["duration"] == "00:00:30.000"


def test_resolve_still_works_without_a_namespace():
    """Some legacy/simple ad servers omit the xmlns -- must keep working too."""
    from webapp.audio_archive.metadata import resolve_stream_url

    with patch("webapp.audio_archive.metadata._is_public_url", return_value=True), \
         patch("webapp.audio_archive.metadata.urllib.request.urlopen",
               return_value=_mock_response("application/xml", _UNNAMESPACED_VAST)):
        result = resolve_stream_url("https://example.com/vast/456")

    assert result["type"] == "vast"
    assert result["audio_url"] == "https://cdn.example.com/ads/legacy.mp3"
    assert result["ad_title"] == "Legacy Ad"


def test_resolve_reports_no_audio_when_vast_has_no_media_file():
    """A VAST Wrapper (or an InLine with no audio Creative) has nothing to play."""
    from webapp.audio_archive.metadata import resolve_stream_url

    empty_vast = b"""<VAST version="4.3" xmlns="http://www.iab.com/VAST">
      <Ad id="1"><InLine><AdSystem>Empty</AdSystem></InLine></Ad>
    </VAST>"""

    with patch("webapp.audio_archive.metadata._is_public_url", return_value=True), \
         patch("webapp.audio_archive.metadata.urllib.request.urlopen",
               return_value=_mock_response("application/xml", empty_vast)):
        result = resolve_stream_url("https://example.com/vast/789")

    assert result["type"] == "vast_no_audio"
    assert "error" in result
