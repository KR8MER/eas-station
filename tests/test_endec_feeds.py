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

"""Unit tests for the Sage-ENDEC-compatible device-feed formatters.

The wire formats validated here come from the Sage Digital ENDEC manual
(§9.1, §9.3, §9.4), summarised in docs/reference/protocols/SAGE_ENDEC.md.
"""

import datetime as dt

import pytest

from app_utils.endec_feeds import (
    ETX,
    EOM_PAYLOAD,
    SAME_PREAMBLE_LEN,
    SAME_SYNC_BYTE,
    STX,
    FeedEvent,
    FeedStatus,
    feed_event_from_payload,
    format_decoder_status,
    format_generic_cgen,
    format_news_feed,
    format_raw_encoder,
    render_feed,
    severity_for_event_code,
)

HEADER = "ZCZC-EAS-RWT-006013+0015-1020624-SAGE -"
TS = dt.datetime(2026, 6, 5, 14, 32, 14, tzinfo=dt.timezone.utc)


def _event(status=FeedStatus.LOCAL.value, **kw):
    base = dict(status=status, event_code="RWT", header=HEADER,
                text="A Broadcast station has issued a Required Weekly Test.",
                timestamp=TS)
    base.update(kw)
    return FeedEvent(**base)


# --- severity --------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    ("TOR", 1),   # Tornado Warning  -> WRN -> most severe
    ("EAN", 1),   # Presidential     -> WRN
    ("TOA", 2),   # Tornado Watch    -> WCH
    ("RWT", 3),   # Weekly Test      -> TEST
    ("ADR", 3),   # Administrative   -> ADV
    ("ZZZ", 3),   # unknown -> default
    ("", 3),      # empty  -> default
    ("tor", 1),   # case-insensitive
])
def test_severity_for_event_code(code, expected):
    assert severity_for_event_code(code) == expected


# --- Generic CGEN: <STX><sev><text><ETX> -----------------------------------

def test_generic_cgen_framing():
    out = format_generic_cgen(_event(event_code="TOR", text="Tornado Warning"))
    assert out[0] == STX
    assert out[1:2] == b"1"          # severity digit for a warning
    assert out[-1] == ETX
    assert out[2:-1] == b"Tornado Warning"


def test_generic_cgen_severity_digit_tracks_event():
    assert format_generic_cgen(_event(event_code="RWT"))[1:2] == b"3"
    assert format_generic_cgen(_event(event_code="TOA"))[1:2] == b"2"


def test_generic_cgen_handles_accented_text():
    # Spanish text must survive as UTF-8 between the control bytes.
    out = format_generic_cgen(_event(text="Notificación"))
    assert out[0] == STX and out[-1] == ETX
    assert out[2:-1].decode("utf-8") == "Notificación"


# --- News Feed: <ENDECSTART> ... <ENDECEND> --------------------------------

def test_news_feed_framing_local():
    text = format_news_feed(_event(status=FeedStatus.LOCAL.value)).decode("utf-8")
    assert text.startswith("<ENDECSTART>\n")
    assert text.rstrip("\n").endswith("<ENDECEND>")
    assert "Local Alert sent at 06/05/26 14:32:14" in text
    assert HEADER in text


def test_news_feed_lead_line_for_received():
    text = format_news_feed(_event(status=FeedStatus.MATCH.value)).decode("utf-8")
    assert "Alert Received at 06/05/26 14:32:14" in text
    assert "Local Alert" not in text


# --- Decoder status: <status>:<zczc>\n<text> -------------------------------

@pytest.mark.parametrize("status", ["local", "match", "nomatch", "dup"])
def test_decoder_status_prefix(status):
    out = format_decoder_status(_event(status=status)).decode("utf-8")
    assert out.startswith(f"{status}:{HEADER}\n")
    assert out.endswith("\n")


def test_decoder_status_without_text():
    out = format_decoder_status(_event(status="nomatch", text="")).decode("utf-8")
    assert out == f"nomatch:{HEADER}\n"


# --- Raw EAS Encoder mirror ------------------------------------------------

def test_raw_encoder_structure():
    out = format_raw_encoder(_event(status=FeedStatus.LOCAL.value))
    preamble = bytes([SAME_SYNC_BYTE]) * SAME_PREAMBLE_LEN
    # 3 header bursts + 3 EOM bursts, each preceded by a 16-byte preamble.
    assert out.count(preamble) == 6
    assert out.count(HEADER.encode("ascii")) == 3
    assert out.count(EOM_PAYLOAD.encode("ascii")) == 3
    assert out.startswith(preamble)


def test_raw_encoder_empty_without_header():
    assert format_raw_encoder(_event(header="")) == b""


# --- render_feed dispatch & encoder gating ---------------------------------

def test_render_feed_dispatch():
    ev = _event(event_code="TOR", text="x")
    assert render_feed("generic_cgen", ev)[0] == STX
    assert render_feed("news_feed", ev).startswith(b"<ENDECSTART>")
    assert render_feed("decoder", ev).startswith(b"local:")


def test_render_feed_encoder_only_emits_for_local():
    # The Encoder device mirrors outgoing alerts only; received statuses are silent.
    assert render_feed("encoder", _event(status="local")) != b""
    assert render_feed("encoder", _event(status="match")) == b""
    assert render_feed("encoder", _event(status="dup")) == b""


def test_render_feed_unknown_format_raises():
    with pytest.raises(ValueError):
        render_feed("not_a_format", _event())


# --- payload round-trip ----------------------------------------------------

def test_feed_event_from_payload():
    ev = feed_event_from_payload({
        "status": "MATCH",
        "event_code": "tor",
        "header": HEADER,
        "text": "hi",
        "timestamp": TS.isoformat(),
    })
    assert ev.status == "match"          # normalised lower
    assert ev.event_code == "TOR"        # normalised upper
    assert ev.severity == 1
    assert ev.timestamp == TS


def test_feed_event_from_payload_bad_timestamp_falls_back():
    ev = feed_event_from_payload({"status": "local", "timestamp": "garbage"})
    assert ev.timestamp.tzinfo is not None
