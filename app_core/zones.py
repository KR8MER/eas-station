"""Helpers for working with the public forecast zone catalog."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from flask import current_app, has_app_context

from app_utils.zone_catalog import (
    ZoneSyncResult,
    iter_zone_records,
    load_zone_records,
    sync_zone_catalog,
)

from .extensions import db
from .models import NWSZone


@dataclass(frozen=True)
class ZoneInfo:
    """Immutable snapshot of a zone definition."""

    code: str
    state_code: str
    zone_number: str
    zone_type: str
    name: str
    short_name: str
    cwa: str
    time_zone: str
    fe_area: str
    latitude: Optional[float]
    longitude: Optional[float]

    def formatted_label(self) -> str:
        label = self.name or self.short_name or self.code
        if self.cwa:
            return f"{self.code} – {label} (WFO {self.cwa})"
        return f"{self.code} – {label}"


_ZONE_LOOKUP_CACHE: Dict[str, ZoneInfo] | None = None
_ZONE_CODE_PATTERN = re.compile(r"^[A-Z]{2}[A-Z][0-9]{3}$")


def _resolve_zone_catalog_path(source_path: str | Path | None) -> Path:
    """Return the path to the zone catalog, respecting config defaults."""

    if source_path:
        return Path(source_path)

    config_path: str | Path | None = None
    if has_app_context():
        config_path = current_app.config.get("NWS_ZONE_DBF_PATH")

    if config_path:
        return Path(config_path)

    return Path("assets/z_05mr24.dbf")


def _log_info(message: str) -> None:
    if has_app_context():
        current_app.logger.info(message)


def _log_warning(message: str) -> None:
    if has_app_context():
        current_app.logger.warning(message)


def clear_zone_lookup_cache() -> None:
    """Invalidate the in-memory zone lookup cache."""

    global _ZONE_LOOKUP_CACHE
    _ZONE_LOOKUP_CACHE = None


def _build_zone_info(model: NWSZone) -> ZoneInfo:
    return ZoneInfo(
        code=model.zone_code,
        state_code=model.state_code,
        zone_number=model.zone_number,
        zone_type=model.zone_type,
        name=model.name,
        short_name=model.short_name or model.name,
        cwa=model.cwa,
        time_zone=model.time_zone or "",
        fe_area=model.fe_area or "",
        latitude=model.latitude,
        longitude=model.longitude,
    )


def get_zone_lookup() -> Dict[str, ZoneInfo]:
    """Return a mapping of zone code to :class:`ZoneInfo`."""

    global _ZONE_LOOKUP_CACHE
    if _ZONE_LOOKUP_CACHE is None:
        _ZONE_LOOKUP_CACHE = {
            zone.zone_code: _build_zone_info(zone)
            for zone in NWSZone.query.all()
        }
    return dict(_ZONE_LOOKUP_CACHE)


def get_zone_info(code: str) -> Optional[ZoneInfo]:
    return get_zone_lookup().get(code.upper().strip())


def normalise_zone_codes(values: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Return normalised zone identifiers and the tokens that were rejected."""

    valid: List[str] = []
    invalid: List[str] = []
    seen = set()

    for value in values:
        token = (value or "").strip().upper()
        if not token:
            continue
        token = token.replace(" ", "").replace("-", "")
        if len(token) == 5 and token[:2].isalpha() and token[2:].isdigit():
            token = f"{token[:2]}Z{token[2:]}"
        if not _ZONE_CODE_PATTERN.fullmatch(token):
            invalid.append(token)
            continue
        if token not in seen:
            seen.add(token)
            valid.append(token)

    return valid, invalid


def split_catalog_members(codes: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Return (known, unknown) codes based on the loaded catalog."""

    lookup = get_zone_lookup()
    known: List[str] = []
    unknown: List[str] = []
    for code in codes:
        if code in lookup:
            known.append(code)
        else:
            unknown.append(code)
    return known, unknown


def format_zone_code_list(codes: Sequence[str]) -> List[str]:
    lookup = get_zone_lookup()
    formatted: List[str] = []
    for code in codes:
        info = lookup.get(code)
        if info:
            formatted.append(info.formatted_label())
        else:
            formatted.append(code)
    return formatted


def ensure_zone_catalog(logger=None, source_path: str | Path | None = None) -> bool:
    """Ensure the zone catalog table matches the bundled DBF file."""

    path = _resolve_zone_catalog_path(source_path)
    if not path.exists():
        _log_warning(f"NOAA zone catalog not found at {path}")
        return False

    records = list(iter_zone_records(path))
    if not records:
        _log_warning(f"Zone catalog at {path} is empty; skipping load")
        return False

    result = sync_zone_catalog(db.session, records, source_path=path)
    clear_zone_lookup_cache()
    summary = (
        "Loaded %d zone records (%d inserted, %d updated, %d removed) from %s"
        % (result.total, result.inserted, result.updated, result.removed, path)
    )
    if logger:
        logger.info(summary)
    else:
        _log_info(summary)
    return True


def synchronise_zone_catalog(
    source_path: str | Path | None = None,
    *,
    dry_run: bool = False,
) -> ZoneSyncResult:
    """Synchronise the zone catalog, optionally in dry-run mode."""

    path = _resolve_zone_catalog_path(source_path)
    records = load_zone_records(path)
    if dry_run:
        return ZoneSyncResult(source_path=path, total=len(records), inserted=0, updated=0, removed=0)

    result = sync_zone_catalog(db.session, records, source_path=path)
    clear_zone_lookup_cache()
    return result


__all__ = [
    "ZoneInfo",
    "clear_zone_lookup_cache",
    "ensure_zone_catalog",
    "format_zone_code_list",
    "get_zone_info",
    "get_zone_lookup",
    "normalise_zone_codes",
    "split_catalog_members",
    "synchronise_zone_catalog",
]
