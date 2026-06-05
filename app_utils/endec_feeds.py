"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

from __future__ import annotations

"""Sage-ENDEC-compatible serial/TCP "device feed" formatters.

These pure functions render an alert event into the byte streams a Sage
Digital ENDEC emits on its assignable serial ports, so existing character
generators and newsroom software can consume EAS Station output unchanged.
The wire formats are documented in
``docs/reference/protocols/SAGE_ENDEC.md`` (manual §9.1, §9.3, §9.4).

Four formats are supported:

* ``generic_cgen``  – Generic Character Generator: ``<STX><sev><text><ETX>``
* ``news_feed``     – Newsroom feed framed with ``<ENDECSTART>…<ENDECEND>``
* ``decoder``       – Decoder status: ``<status>:<zczc>\\n<expanded text>``
* ``encoder``       – Raw EAS byte mirror (``0xAB`` preamble + ZCZC / NNNN)

Everything here is transport-agnostic and side-effect-free; the TCP fan-out
lives in :mod:`services.endec_feeds`.
"""

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Optional

from app_utils.event_codes import EVENT_CODE_REGISTRY

# --- Control bytes / framing constants -------------------------------------

STX = 0x02
ETX = 0x03

#: SAME synchronisation byte (shown as ``+`` in the Sage manual's dumps).
SAME_SYNC_BYTE = 0xAB
#: Preamble length that precedes each SAME burst (manual §9.1 samples).
SAME_PREAMBLE_LEN = 16
#: End-of-message payload (FCC 47 CFR §11.31(c)).
EOM_PAYLOAD = "NNNN"
#: Number of header / EOM repetitions in an on-air burst.
SAME_BURST_COUNT = 3

NEWS_FEED_START = "<ENDECSTART>"
NEWS_FEED_END = "<ENDECEND>"

#: Severity tier per event-code "product" class. 1 = most severe (drives the
#: red/most-urgent colour on character generators and LED signs), 3 = least.
_SEVERITY_BY_PRODUCT: Dict[str, int] = {"WRN": 1, "WCH": 2, "ADV": 3, "TEST": 3}
DEFAULT_SEVERITY = 3


class FeedFormat(str, Enum):
    """Identifiers for the supported device-feed wire formats."""

    GENERIC_CGEN = "generic_cgen"
    NEWS_FEED = "news_feed"
    DECODER = "decoder"
    ENCODER = "encoder"


class FeedStatus(str, Enum):
    """Decoder-status values (manual §9.1)."""

    LOCAL = "local"      # an alert is being sent by this station
    MATCH = "match"      # heard, and it matched an input filter
    NOMATCH = "nomatch"  # heard, but matched no filter
    DUP = "dup"          # already heard / already broadcast


#: All valid format identifiers, handy for config validation and UI lists.
FEED_FORMATS = tuple(fmt.value for fmt in FeedFormat)
#: All valid status identifiers.
FEED_STATUSES = tuple(status.value for status in FeedStatus)


def severity_for_event_code(event_code: Optional[str]) -> int:
    """Map a SAME event code to a 1–3 severity tier for display devices.

    Derived from the event's product class in
    :data:`app_utils.event_codes.EVENT_CODE_REGISTRY` (warnings → 1,
    watches → 2, advisories/tests → 3). Unknown codes default to 3.
    """
    if not event_code:
        return DEFAULT_SEVERITY
    entry = EVENT_CODE_REGISTRY.get(event_code.strip().upper())
    if not entry:
        return DEFAULT_SEVERITY
    product = str(entry.get("default_product", "")).upper()
    return _SEVERITY_BY_PRODUCT.get(product, DEFAULT_SEVERITY)


@dataclass
class FeedEvent:
    """A single decoder/encoder event to render onto a device feed.

    ``header`` is the raw ``ZCZC-…`` SAME string (may be empty for events
    decoded without a clean header); ``text`` is the human-readable
    plain-language expansion produced elsewhere in the pipeline.
    """

    status: str
    event_code: str = ""
    header: str = ""
    text: str = ""
    station_id: str = ""
    timestamp: _dt.datetime = field(
        default_factory=lambda: _dt.datetime.now(_dt.timezone.utc)
    )

    @property
    def severity(self) -> int:
        return severity_for_event_code(self.event_code)


def _encode_text(text: str) -> bytes:
    """Encode display text. UTF-8 keeps accented (Spanish) characters intact."""
    return (text or "").encode("utf-8", "replace")


def _same_preamble() -> bytes:
    return bytes([SAME_SYNC_BYTE] * SAME_PREAMBLE_LEN)


# --- Formatters ------------------------------------------------------------

def format_generic_cgen(event: FeedEvent) -> bytes:
    """Generic Character Generator frame: ``<STX><sev><text><ETX>`` (manual §9.3)."""
    sev_byte = str(event.severity).encode("ascii")  # '1' / '2' / '3'
    return bytes([STX]) + sev_byte + _encode_text(event.text) + bytes([ETX])


def _news_lead_line(event: FeedEvent) -> str:
    timestamp = event.timestamp.strftime("%m/%d/%y %H:%M:%S")
    if event.status == FeedStatus.LOCAL.value:
        return f"Local Alert sent at {timestamp}"
    return f"Alert Received at {timestamp}"


def format_news_feed(event: FeedEvent) -> bytes:
    """Newsroom feed block framed by ``<ENDECSTART>``/``<ENDECEND>`` (manual §9.4)."""
    parts = [NEWS_FEED_START, _news_lead_line(event)]
    if event.text:
        parts.append(event.text)
    if event.header:
        parts.append(event.header)
    parts.append(NEWS_FEED_END)
    return ("\n".join(parts) + "\n").encode("utf-8", "replace")


def format_decoder_status(event: FeedEvent) -> bytes:
    """Decoder status line: ``<status>:<zczc>`` then the expanded text (manual §9.1)."""
    body = f"{event.status}:{event.header}"
    if event.text:
        body += "\n" + event.text
    return (body + "\n").encode("utf-8", "replace")


def format_raw_encoder(event: FeedEvent, *, burst_count: int = SAME_BURST_COUNT) -> bytes:
    """Raw EAS "Encoder" byte mirror of an outgoing alert (manual §9.1).

    Emits ``burst_count`` × (preamble + ``ZCZC…`` header) followed by
    ``burst_count`` × (preamble + ``NNNN`` EOM), matching the on-air byte
    sequence the Sage Encoder device echoes when the box transmits. Returns
    empty bytes when there is no header to mirror.
    """
    if not event.header:
        return b""
    out = bytearray()
    header_bytes = event.header.encode("ascii", "replace")
    eom_bytes = EOM_PAYLOAD.encode("ascii")
    for _ in range(burst_count):
        out += _same_preamble()
        out += header_bytes
    for _ in range(burst_count):
        out += _same_preamble()
        out += eom_bytes
    return bytes(out)


_FORMATTERS: Dict[str, Callable[[FeedEvent], bytes]] = {
    FeedFormat.GENERIC_CGEN.value: format_generic_cgen,
    FeedFormat.NEWS_FEED.value: format_news_feed,
    FeedFormat.DECODER.value: format_decoder_status,
    FeedFormat.ENCODER.value: format_raw_encoder,
}


def render_feed(feed_format: str, event: FeedEvent) -> bytes:
    """Render ``event`` for ``feed_format``.

    The raw ``encoder`` mirror only applies to outgoing (``local``) alerts —
    for received-alert statuses it returns empty bytes so nothing is sent.
    Raises :class:`ValueError` for an unknown format.
    """
    fmt = (feed_format or "").strip().lower()
    formatter = _FORMATTERS.get(fmt)
    if formatter is None:
        raise ValueError(f"Unknown ENDEC feed format: {feed_format!r}")
    if fmt == FeedFormat.ENCODER.value and event.status != FeedStatus.LOCAL.value:
        return b""
    return formatter(event)


def _parse_timestamp(raw: object) -> _dt.datetime:
    if isinstance(raw, _dt.datetime):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return _dt.datetime.fromisoformat(raw)
        except ValueError:
            pass
    return _dt.datetime.now(_dt.timezone.utc)


def feed_event_from_payload(payload: Dict[str, object]) -> FeedEvent:
    """Build a :class:`FeedEvent` from a Redis JSON payload (see the publisher)."""
    return FeedEvent(
        status=str(payload.get("status", "")).strip().lower(),
        event_code=str(payload.get("event_code", "")).strip().upper(),
        header=str(payload.get("header", "")),
        text=str(payload.get("text", "")),
        station_id=str(payload.get("station_id", "")),
        timestamp=_parse_timestamp(payload.get("timestamp")),
    )


__all__ = [
    "STX", "ETX", "SAME_SYNC_BYTE", "SAME_PREAMBLE_LEN", "EOM_PAYLOAD",
    "SAME_BURST_COUNT", "NEWS_FEED_START", "NEWS_FEED_END", "DEFAULT_SEVERITY",
    "FeedFormat", "FeedStatus", "FEED_FORMATS", "FEED_STATUSES",
    "FeedEvent", "severity_for_event_code",
    "format_generic_cgen", "format_news_feed", "format_decoder_status",
    "format_raw_encoder", "render_feed", "feed_event_from_payload",
]
