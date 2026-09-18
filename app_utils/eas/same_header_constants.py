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

"""Static lookup tables for SAME header decode/describe: originator, purge-time,
NRSC-4-B field, and P-digit reference data."""

from typing import Tuple

from app_utils.fips_codes import P_DIGIT_LABELS

P_DIGIT_MEANINGS = dict(P_DIGIT_LABELS)



ORIGINATOR_DESCRIPTIONS = {
    'EAS': 'EAS Participant / broadcaster',
    'CIV': 'Civil authorities',
    'WXR': 'National Weather Service',
    'PEP': 'National Public Warning System (PEP)',
}



# County abbreviations for Lima Ohio EAS Operational Area
COUNTY_ABBREVIATIONS = {
    'ALLE': 'Allen',
    'AUGL': 'Auglaize',
    'HANC': 'Hancock',
    'HARD': 'Hardin',
    'MERC': 'Mercer',
    'PAUL': 'Paulding',
    'PUTN': 'Putnam',
    'VANW': 'Van Wert',
}



PRIMARY_ORIGINATORS: Tuple[str, ...] = ('EAS', 'CIV', 'WXR', 'PEP')



# NRSC-4-B §4.3.3.4 — exactly fourteen valid purge-time HHMM values.
# Times are encoded as HHMM (hours and minutes), not decimal minutes.
# 15-minute increments up to 0045; 30-minute increments from 0100 to 0600.
NRSC4B_VALID_PURGE_TIMES: Tuple[str, ...] = (
    '0015', '0030', '0045',
    '0100', '0130',
    '0200', '0230',
    '0300', '0330',
    '0400', '0430',
    '0500', '0530',
    '0600',
)



# NRSC-4-B §4.3.3.3 — maximum number of location codes in a single header.
NRSC4B_MAX_LOCATIONS: int = 31



# NRSC-4-B §4.3.3.2 — valid originator codes.
NRSC4B_VALID_ORIGINATORS: Tuple[str, ...] = PRIMARY_ORIGINATORS



# NRSC-4-B §4.3.3.7 — station identifier length (characters, excluding delimiters).
NRSC4B_STATION_ID_MAX_LEN: int = 8



# NRSC-4-B §4.2 — preamble byte value and repetition count.
NRSC4B_PREAMBLE_BYTE: int = 0xAB


NRSC4B_PREAMBLE_COUNT: int = 16



# NRSC-4-B §4.4 — FSK physical-layer constants.
# Baud rate: exactly 25000/48 = 520.833... symbols/second per NRSC-4-B §4.4.
NRSC4B_BAUD_RATE_FRAC: str = '25000/48'  # exact rational representation (≈ 520.83 baud)


NRSC4B_MARK_FREQ_HZ: float = 2083.0 + 1.0 / 3.0   # 2083 1/3 Hz


NRSC4B_SPACE_FREQ_HZ: float = 1562.5                # 1562.5 Hz


NRSC4B_CENTER_FREQ_HZ: float = 1822.916666          # midpoint (mark+space)/2



# NRSC-4-B §4.5 — triple-burst transmission count.
NRSC4B_BURST_COUNT: int = 3




SAME_HEADER_FIELD_DESCRIPTIONS = [
    {
        'segment': 'Preamble',
        'label': '16 × 0xAB',
        'nrsc4b_section': '§4.2',
        'description': (
            'Sixteen bytes of 0xAB (10101011 binary) transmitted before the ASCII header '
            'to calibrate and synchronise receivers.  Each byte is sent LSB-first with no '
            'start or stop framing, giving a 128-bit alternating mark/space pattern.'
        ),
    },
    {
        'segment': 'ZCZC',
        'label': 'Start code',
        'nrsc4b_section': '§4.3.2',
        'description': (
            'Four ASCII characters marking the start of the SAME header.  '
            'Inherited from NAVTEX to trigger automatic decoders.  '
            'Always the literal string "ZCZC" with no leading dash.'
        ),
    },
    {
        'segment': 'ORG',
        'label': 'Originator code',
        'nrsc4b_section': '§4.3.3.2',
        'description': (
            'Three-character code identifying who issued the alert.  '
            'Valid values: EAS (EAS Participant/broadcaster), CIV (Civil authorities), '
            'WXR (National Weather Service), PEP (National Public Warning System).'
        ),
        'valid_values': list(NRSC4B_VALID_ORIGINATORS),
    },
    {
        'segment': 'EEE',
        'label': 'Event code',
        'nrsc4b_section': '§4.3.3.3',
        'description': (
            'Three-character SAME event code describing the hazard (e.g. TOR, FFW, RWT).  '
            'Codes are maintained by FEMA/IPAWS and published in the FCC Part 11 rules.'
        ),
    },
    {
        'segment': 'PSSCCC',
        'label': 'Location codes',
        'nrsc4b_section': '§4.3.3.3',
        'description': (
            'One to thirty-one six-digit SAME/FIPS location identifiers separated by dashes.  '
            'P (1 digit) = geographic subset (0 = entire area, 1–9 = compass octant).  '
            'SS (2 digits) = state FIPS code.  '
            'CCC (3 digits) = county FIPS code (000 = entire state).'
        ),
        'max_count': NRSC4B_MAX_LOCATIONS,
    },
    {
        'segment': '+TTTT',
        'label': 'Purge time',
        'nrsc4b_section': '§4.3.3.4',
        'description': (
            'Four-digit HHMM duration code indicating how long the alert is valid.  '
            'Valid values are 0015 through 0600 in the increments defined by NRSC-4-B: '
            '15-minute steps up to 45 minutes, then 30-minute steps up to 6 hours.'
        ),
        'valid_values': list(NRSC4B_VALID_PURGE_TIMES),
    },
    {
        'segment': '-JJJHHMM',
        'label': 'Issue time',
        'nrsc4b_section': '§4.3.3.5',
        'description': (
            'Seven-digit UTC issue timestamp: JJJ = Julian day of year (001–366), '
            'HH = hour (00–23), MM = minute (00–59).  '
            'Year is not encoded; receivers infer it from the current calendar year.'
        ),
    },
    {
        'segment': '-LLLLLLLL-',
        'label': 'Station identifier',
        'nrsc4b_section': '§4.3.3.6',
        'description': (
            'Eight-character call-sign or system identifier for the originating station, '
            'padded with hyphens if shorter.  Slashes may substitute for hyphens inside '
            'the identifier.  Terminated by a trailing hyphen delimiter.'
        ),
        'max_length': NRSC4B_STATION_ID_MAX_LEN,
    },
    {
        'segment': 'NNNN',
        'label': 'End of message',
        'nrsc4b_section': '§4.3.4',
        'description': (
            'End Of Message marker transmitted three times after audio content to '
            'terminate the activation.  Each EOM burst consists of the standard '
            'preamble followed by the ASCII string "NNNN" with no trailing CR.'
        ),
    },
]




# Six independent NRSC-4-B field checks emitted by ``describe_same_header``.
# Each one that passes means a distinct byte group decoded into a value that is
# valid per the spec — strong, decode-*correctness* evidence that the raw per-bit
# tone margin cannot provide.
_NRSC4B_FIELD_FLAGS: Tuple[str, ...] = (
    'nrsc4b_valid_originator',
    'nrsc4b_valid_event',
    'nrsc4b_valid_purge',
    'nrsc4b_valid_issue_time',
    'nrsc4b_valid_location_count',
    'nrsc4b_valid_station_id',
)
