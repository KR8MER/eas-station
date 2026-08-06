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

from __future__ import annotations

"""Static RBDS/RDS reference tables and PI-code decoding.

RT+ application identifier and content types (RDS Forum R03/040.1), RBDS
language codes (IEC 62106) and the NRSC-4-B call-sign mapping.
"""

from typing import Dict, Optional


# RT+ (RadioText Plus) ODA Application Identifier per RDS Forum R03/040.1.
# Stations broadcast it on the group type assigned in their Group 3A
# registration (most US music stations use 11A, some use 12A).
RT_PLUS_AID = 0xCD46

# Content type codes from the RT+ specification (R03/040.1 §6.2 Table 1).
# Codes 0 and >= 53 are dummy / reserved-for-future-use; we still expose
# the raw code so receivers can render unknown classes generically.
RT_PLUS_CONTENT_TYPES: Dict[int, str] = {
    0: "DUMMY", 1: "ITEM.TITLE", 2: "ITEM.ALBUM", 3: "ITEM.TRACKNUMBER",
    4: "ITEM.ARTIST", 5: "ITEM.COMPOSITION", 6: "ITEM.MOVEMENT",
    7: "ITEM.CONDUCTOR", 8: "ITEM.COMPOSER", 9: "ITEM.BAND",
    10: "ITEM.COMMENT", 11: "ITEM.GENRE", 12: "INFO.NEWS",
    13: "INFO.NEWS.LOCAL", 14: "INFO.STOCKMARKET", 15: "INFO.SPORT",
    16: "INFO.LOTTERY", 17: "INFO.HOROSCOPE", 18: "INFO.DAILY_DIVERSION",
    19: "INFO.HEALTH", 20: "INFO.EVENT", 21: "INFO.SCENE",
    22: "INFO.CINEMA", 23: "INFO.TV", 24: "INFO.DATE_TIME",
    25: "INFO.WEATHER", 26: "INFO.TRAFFIC", 27: "INFO.ALARM",
    28: "INFO.ADVERTISEMENT", 29: "INFO.URL", 30: "INFO.OTHER",
    31: "STATIONNAME.SHORT", 32: "STATIONNAME.LONG",
    33: "PROGRAMME.NOW", 34: "PROGRAMME.NEXT", 35: "PROGRAMME.PART",
    36: "PROGRAMME.HOST", 37: "PROGRAMME.EDITORIAL_STAFF",
    38: "PROGRAMME.FREQUENCY", 39: "PROGRAMME.HOMEPAGE",
    40: "PROGRAMME.SUBCHANNEL", 41: "PHONE.HOTLINE",
    42: "PHONE.STUDIO", 43: "PHONE.OTHER", 44: "SMS.STUDIO",
    45: "SMS.OTHER", 46: "EMAIL.HOTLINE", 47: "EMAIL.STUDIO",
    48: "EMAIL.OTHER", 49: "MMS.OTHER", 50: "CHAT", 51: "CHAT.CENTRE",
    52: "VOTE.QUESTION", 53: "VOTE.CENTRE",
    58: "PLACE", 59: "APPOINTMENT", 60: "IDENTIFIER",
    61: "PURCHASE", 62: "GET_DATA",
}


RBDS_LANGUAGE_CODES: Dict[int, str] = {
    0x01: "Albanian", 0x02: "Breton", 0x03: "Catalan", 0x04: "Croatian",
    0x05: "Welsh", 0x06: "Czech", 0x07: "Danish", 0x08: "German",
    0x09: "English", 0x0A: "Spanish", 0x0B: "Esperanto", 0x0C: "Estonian",
    0x0D: "Basque", 0x0E: "Faroese", 0x0F: "French", 0x10: "Frisian",
    0x11: "Irish", 0x12: "Gaelic", 0x13: "Galician", 0x14: "Icelandic",
    0x15: "Italian", 0x16: "Lappish", 0x17: "Latin", 0x18: "Latvian",
    0x19: "Luxembourgian", 0x1A: "Lithuanian", 0x1B: "Hungarian",
    0x1C: "Macedonian", 0x1D: "Maltese", 0x1E: "Norwegian", 0x1F: "Occitan",
    0x20: "Polish", 0x21: "Portuguese", 0x22: "Romanian", 0x23: "Romansh",
    0x24: "Serbian", 0x25: "Slovak", 0x26: "Slovene", 0x27: "Finnish",
    0x28: "Swedish", 0x29: "Turkish", 0x2A: "Flemish", 0x2B: "Walloon",
    0x40: "Background sound", 0x45: "Zulu", 0x46: "Vietnamese", 0x47: "Uzbek",
    0x48: "Urdu", 0x49: "Ukrainian", 0x4A: "Thai", 0x4B: "Telugu",
    0x4C: "Tatar", 0x4D: "Tamil", 0x4E: "Tajik", 0x4F: "Swahili",
    0x50: "Sranan Tongo", 0x51: "Somali", 0x52: "Sinhalese", 0x53: "Shona",
    0x54: "Serbo-Croat", 0x55: "Ruthenian", 0x56: "Russian", 0x57: "Quechua",
    0x58: "Pushtu", 0x59: "Punjabi", 0x5A: "Persian", 0x5B: "Papamiento",
    0x5C: "Oriya", 0x5D: "Nepali", 0x5E: "Ndebele", 0x5F: "Marathi",
    0x60: "Moldovian", 0x61: "Malaysian", 0x62: "Malagasy", 0x63: "Macedonian",
    0x64: "Laotian", 0x65: "Korean", 0x66: "Khmer", 0x67: "Kazakh",
    0x68: "Kannada", 0x69: "Japanese", 0x6A: "Indonesian", 0x6B: "Hindi",
    0x6C: "Hebrew", 0x6D: "Hausa", 0x6E: "Gurani", 0x6F: "Gujurati",
    0x70: "Greek", 0x71: "Georgian", 0x72: "Fulah", 0x73: "Dari",
    0x74: "Churash", 0x75: "Chinese", 0x76: "Burmese", 0x77: "Bulgarian",
    0x78: "Bengali", 0x79: "Belorussian", 0x7A: "Bambora", 0x7B: "Azerbaijani",
    0x7C: "Assamese", 0x7D: "Armenian", 0x7E: "Arabic", 0x7F: "Amharic",
}


# NRSC-4-B Annex D.3: 3-letter US legacy call signs with explicitly
# assigned PI codes. Limited to well-known FM-active stations; anything
# unlisted falls through to the 4-letter algorithmic decode or None.
_NRSC4_THREE_LETTER_CALLSIGNS: Dict[int, str] = {
    0x99A5: "KDKA",
    0x9990: "KYW",
    0x9950: "WBZ",
    0x9952: "WGY",
    0x9953: "WHA",
    0x9955: "WHAS",
    0x9959: "WHO",
    0x9974: "WOC",
    0x9988: "WRR",
    0x9992: "WSB",
    0x9993: "WSM",
    0x9997: "WWJ",
    0x9999: "WWL",
}


def pi_to_call_sign(pi: int) -> Optional[str]:
    """Translate a 16-bit RBDS PI code to US call letters (NRSC-4-B Annex D).

    4-letter call signs are derived algorithmically:
        K-prefix: PI = 0x1000 + 676*(L2) + 26*(L3) + (L4)   → 0x1000..0x54A7
        W-prefix: PI = 0x54A8 + 676*(L2) + 26*(L3) + (L4)   → 0x54A8..0x994F
    where L2/L3/L4 are zero-based alphabetic indices (A=0, ..., Z=25).

    A small set of 3-letter legacy calls have explicit PI assignments
    in Annex D.3 and take precedence over the algorithmic range.

    Returns None if the PI code falls outside the NRSC-4 US allocation
    (e.g. European RDS codes where the high nibble is a country code),
    since those would decode into nonsense call letters.
    """
    if pi in _NRSC4_THREE_LETTER_CALLSIGNS:
        return _NRSC4_THREE_LETTER_CALLSIGNS[pi]

    if 0x1000 <= pi <= 0x994F:
        if pi < 0x54A8:
            prefix = "K"
            charsum = pi - 0x1000
        else:
            prefix = "W"
            charsum = pi - 0x54A8
        l2, rem = divmod(charsum, 676)
        l3, l4 = divmod(rem, 26)
        return prefix + chr(ord("A") + l2) + chr(ord("A") + l3) + chr(ord("A") + l4)

    return None

