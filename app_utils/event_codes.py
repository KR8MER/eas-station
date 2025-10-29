"""Registry and helper utilities for SAME/EAS event codes."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set


def _entry(name: str, *, default_product: str, aliases: Optional[Sequence[str]] = None) -> Dict[str, object]:
    alias_list = list(aliases or [])
    return {
        'name': name,
        'default_product': default_product,
        'aliases': alias_list,
    }


EVENT_CODE_REGISTRY: Dict[str, Dict[str, object]] = {
    'ADR': _entry('Administrative Message', default_product='ADV'),
    'AVA': _entry('Avalanche Watch', default_product='WCH'),
    'AVW': _entry('Avalanche Warning', default_product='WRN'),
    'BZW': _entry('Blizzard Warning', default_product='WRN'),
    'CAE': _entry('Child Abduction Emergency', default_product='ADV', aliases=['Amber Alert']),
    'CDW': _entry('Civil Danger Warning', default_product='WRN'),
    'CEM': _entry('Civil Emergency Message', default_product='WRN'),
    'CFA': _entry('Coastal Flood Watch', default_product='WCH'),
    'CFW': _entry('Coastal Flood Warning', default_product='WRN'),
    'DMO': _entry('Practice/Demo Warning', default_product='TEST', aliases=['Demo Warning']),
    'DSW': _entry('Dust Storm Warning', default_product='WRN'),
    'EAN': _entry('Emergency Action Notification', default_product='WRN'),
    'EAT': _entry('Emergency Action Termination', default_product='ADV'),
    'EQW': _entry('Earthquake Warning', default_product='WRN'),
    'EVI': _entry('Evacuation Immediate', default_product='WRN'),
    'FFA': _entry('Flash Flood Watch', default_product='WCH'),
    'FFS': _entry('Flash Flood Statement', default_product='ADV'),
    'FFW': _entry('Flash Flood Warning', default_product='WRN'),
    'FLA': _entry('Flood Watch', default_product='WCH'),
    'FLS': _entry('Flood Statement', default_product='ADV'),
    'FLW': _entry('Flood Warning', default_product='WRN'),
    'FRW': _entry('Fire Warning', default_product='WRN'),
    'HLS': _entry('Hurricane Local Statement', default_product='ADV'),
    'HMW': _entry('Hazardous Materials Warning', default_product='WRN'),
    'HUA': _entry('Hurricane Watch', default_product='WCH'),
    'HUW': _entry('Hurricane Warning', default_product='WRN'),
    'HWA': _entry('High Wind Watch', default_product='WCH'),
    'HWW': _entry('High Wind Warning', default_product='WRN'),
    'LAE': _entry('Local Area Emergency', default_product='ADV'),
    'LEW': _entry('Law Enforcement Warning', default_product='WRN'),
    'NIC': _entry('National Information Center', default_product='ADV'),
    'NMN': _entry('Network Message Notification', default_product='ADV'),
    'NPT': _entry('National Periodic Test', default_product='TEST'),
    'NUW': _entry('Nuclear Power Plant Warning', default_product='WRN'),
    'RHW': _entry('Radiological Hazard Warning', default_product='WRN'),
    'RMT': _entry('Required Monthly Test', default_product='TEST'),
    'RWT': _entry('Required Weekly Test', default_product='TEST'),
    'SMW': _entry('Special Marine Warning', default_product='WRN'),
    'SPS': _entry('Special Weather Statement', default_product='ADV'),
    'SPW': _entry('Shelter in Place Warning', default_product='WRN'),
    'SVA': _entry('Severe Thunderstorm Watch', default_product='WCH'),
    'SVR': _entry('Severe Thunderstorm Warning', default_product='WRN'),
    'SVS': _entry('Severe Weather Statement', default_product='ADV'),
    'TOA': _entry('Tornado Watch', default_product='WCH'),
    'TOE': _entry('911 Telephone Outage Emergency', default_product='ADV'),
    'TOR': _entry('Tornado Warning', default_product='WRN', aliases=['Tornado Emergency']),
    'TRA': _entry('Tropical Storm Watch', default_product='WCH'),
    'TRW': _entry('Tropical Storm Warning', default_product='WRN'),
    'TSA': _entry('Tsunami Watch', default_product='WCH'),
    'TSW': _entry('Tsunami Warning', default_product='WRN'),
    'VOW': _entry('Volcano Warning', default_product='WRN'),
    'WSA': _entry('Winter Storm Watch', default_product='WCH'),
    'WSW': _entry('Winter Storm Warning', default_product='WRN'),
}


ALL_EVENT_CODES: Sequence[str] = tuple(sorted(EVENT_CODE_REGISTRY))

EVENT_CODE_ALLOW_ALL_TOKENS: Set[str] = {'ALL', 'ANY', '*'}

EVENT_CODE_PRESET_TOKENS: Mapping[str, Set[str]] = {
    'TEST': {'RWT', 'RMT', 'DMO', 'NPT'},
    'TESTS': {'RWT', 'RMT', 'DMO', 'NPT'},
}

DEFAULT_EVENT_CODES: Set[str] = set(ALL_EVENT_CODES)


def normalise_event_code(value: str) -> Optional[str]:
    if not value:
        return None
    cleaned = ''.join(ch for ch in value.upper() if ch.isalnum() or ch == '?')
    if len(cleaned) != 3:
        return None
    return cleaned


def _normalise_name(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


EVENT_NAME_LOOKUP: Dict[str, str] = {}
for code, entry in EVENT_CODE_REGISTRY.items():
    EVENT_NAME_LOOKUP[_normalise_name(entry['name'])] = code
    for alias in entry.get('aliases', []):
        EVENT_NAME_LOOKUP[_normalise_name(alias)] = code


def resolve_event_code_from_name(name: str) -> Optional[str]:
    if not name:
        return None
    return EVENT_NAME_LOOKUP.get(_normalise_name(name))


def resolve_event_code(event_name: str, candidates: Sequence[str]) -> str:
    for candidate in candidates:
        normalised = normalise_event_code(candidate)
        if normalised and normalised in EVENT_CODE_REGISTRY:
            return normalised

    by_name = resolve_event_code_from_name(event_name)
    if by_name:
        return by_name

    return 'CEM'


def describe_event_code(code: str) -> str:
    data = EVENT_CODE_REGISTRY.get(code)
    if not data:
        return code
    return f"{code} ({data['name']})"


def normalise_event_tokens(values: Iterable[str]) -> Set[str]:
    resolved: Set[str] = set()
    allow_all = False

    for value in values:
        token = value.strip()
        if not token:
            continue
        upper = token.upper()
        if upper in EVENT_CODE_ALLOW_ALL_TOKENS:
            allow_all = True
            continue
        if upper in EVENT_CODE_PRESET_TOKENS:
            resolved.update(EVENT_CODE_PRESET_TOKENS[upper])
            continue
        code = normalise_event_code(token)
        if code:
            resolved.add(code)
            continue

    if allow_all:
        return set(ALL_EVENT_CODES)

    return resolved


def format_event_code_list(codes: Sequence[str]) -> List[str]:
    formatted: List[str] = []
    for code in codes:
        formatted.append(describe_event_code(code))
    return formatted


__all__ = [
    'ALL_EVENT_CODES',
    'DEFAULT_EVENT_CODES',
    'EVENT_CODE_ALLOW_ALL_TOKENS',
    'EVENT_CODE_PRESET_TOKENS',
    'EVENT_CODE_REGISTRY',
    'describe_event_code',
    'format_event_code_list',
    'normalise_event_code',
    'normalise_event_tokens',
    'resolve_event_code',
    'resolve_event_code_from_name',
]

