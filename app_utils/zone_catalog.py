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

"""Utilities for working with the NOAA public forecast zone catalog."""

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple, Union

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ZoneRecord:
    """A single entry from the NOAA public forecast zone DBF export."""

    zone_code: str
    state_code: str
    zone_number: str
    cwa: str
    time_zone: str
    fe_area: str
    name: str
    state_zone: str
    longitude: Optional[float]
    latitude: Optional[float]
    short_name: str

    @property
    def zone_type(self) -> str:
        """Public forecast zones all use the ``Z`` type identifier."""

        return "Z"


@dataclass(frozen=True)
class CountySubdivisionRecord:
    """A partial county definition sourced from the FEMA SAME catalog."""

    state_code: str
    cwa: str
    county_name: str
    fips: str
    time_zone: str
    fe_area: str
    longitude: Optional[float]
    latitude: Optional[float]
    entire_same: str
    area_same: str
    area_name: str


@dataclass(frozen=True)
class ZoneSyncResult:
    """Summary information returned after synchronising the catalog."""

    source_path: Path
    total: int
    inserted: int
    updated: int
    removed: int


class _DBFHeader:
    __slots__ = ("record_count", "header_length", "record_length")

    def __init__(self, record_count: int, header_length: int, record_length: int) -> None:
        self.record_count = record_count
        self.header_length = header_length
        self.record_length = record_length


class _DBFField:
    __slots__ = ("name", "type", "length", "decimal_count")

    def __init__(self, name: str, field_type: str, length: int, decimal_count: int) -> None:
        self.name = name
        self.type = field_type
        self.length = length
        self.decimal_count = decimal_count


def _read_header(handle) -> Tuple[_DBFHeader, List[_DBFField]]:
    header_bytes = handle.read(32)
    if len(header_bytes) != 32:
        raise ValueError("File is too small to be a valid DBF table.")

    _, _, _, _, record_count, header_length, record_length = struct.unpack(
        "<BBBBIHH20x", header_bytes
    )

    fields: List[_DBFField] = []
    while True:
        descriptor = handle.read(32)
        if not descriptor:
            raise ValueError("DBF file ended before the field terminator was found.")
        if descriptor[0] == 0x0D:
            break
        name_raw = descriptor[:11].split(b"\x00", 1)[0]
        field_name = name_raw.decode("ascii", errors="ignore").strip()
        field_type = chr(descriptor[11])
        length = descriptor[16]
        decimal_count = descriptor[17]
        fields.append(_DBFField(field_name, field_type, length, decimal_count))

    return _DBFHeader(record_count, header_length, record_length), fields


def _decode_string(raw: bytes) -> str:
    return raw.decode("latin-1", errors="ignore").strip()


def _decode_float(raw: bytes) -> Optional[float]:
    text = _decode_string(raw)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalise_zone_number(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return "000"
    return digits.zfill(3)[:3]


def _detect_zone_schema(field_map: Dict[str, "_DBFField"]) -> str:
    """Return ``"public"`` or ``"marine"`` based on the DBF's columns.

    Public forecast zone DBFs (``z_*.dbf``) carry the full per-record
    state/zone breakdown (``STATE``, ``ZONE``, ``CWA``, …). Marine zone
    DBFs (``mz_*.dbf``) use a much narrower schema (``ID``, ``WFO``,
    ``GL_WFO``, ``NAME``, ``LON``, ``LAT``) — the alphanumeric UGC code
    sits in ``ID`` already and there is no per-state breakdown to read.

    Raises ``ValueError`` if neither schema is recognisable so the
    operator gets an actionable error instead of silent partial data.
    """

    has_public = all(name in field_map for name in ("STATE", "ZONE", "NAME"))
    has_marine = all(name in field_map for name in ("ID", "NAME", "WFO"))
    if has_public:
        return "public"
    if has_marine:
        return "marine"
    raise ValueError(
        "Unrecognised zone DBF schema. Expected public-zone columns "
        "(STATE, ZONE, CWA, NAME, …) or marine-zone columns "
        "(ID, WFO, NAME, LON, LAT). Got: "
        + ", ".join(sorted(field_map.keys()))
    )


def _parse_public_record(values: Dict[str, bytes]) -> ZoneRecord:
    state = _decode_string(values["STATE"]).upper()
    zone_number = _normalise_zone_number(_decode_string(values["ZONE"]))
    zone_code = f"{state}Z{zone_number}" if state else zone_number
    state_zone = _decode_string(values.get("STATE_ZONE", b"")).upper()
    if not state_zone and state:
        state_zone = f"{state}{zone_number}"

    return ZoneRecord(
        zone_code=zone_code,
        state_code=state,
        zone_number=zone_number,
        cwa=_decode_string(values.get("CWA", b"")).upper(),
        time_zone=_decode_string(values.get("TIME_ZONE", b"")).upper(),
        fe_area=_decode_string(values.get("FE_AREA", b"")).upper(),
        name=_decode_string(values["NAME"]),
        state_zone=state_zone,
        longitude=_decode_float(values.get("LON", b"")),
        latitude=_decode_float(values.get("LAT", b"")),
        short_name=_decode_string(values.get("SHORTNAME", b"")),
    )


def _parse_marine_record(values: Dict[str, bytes]) -> Optional[ZoneRecord]:
    raw_id = _decode_string(values.get("ID", b"")).upper()
    if len(raw_id) < 3:
        return None  # Not a valid UGC zone code.

    # UGC zone codes are ``XXY###`` — two-letter regional prefix (``PS``,
    # ``GM``, ``AM``, …), one-letter type (``Z`` for forecast zones), and
    # a three-digit zone number. We store the alphabetic prefix in
    # ``state_code`` so :func:`fips_codes.get_marine_state_tree` can find
    # marine entries with a simple ``state_code IN (...)`` filter.
    prefix = raw_id[:2]
    zone_type_char = raw_id[2:3] if raw_id[2:3].isalpha() else "Z"
    zone_number = _normalise_zone_number(raw_id[3:])
    zone_code = raw_id if len(raw_id) <= 6 else f"{prefix}{zone_type_char}{zone_number}"

    # Prefer the Great-Lakes-specific WFO column when populated.
    gl_wfo = _decode_string(values.get("GL_WFO", b"")).upper()
    wfo = gl_wfo or _decode_string(values.get("WFO", b"")).upper()

    return ZoneRecord(
        zone_code=zone_code[:6],
        state_code=prefix,
        zone_number=zone_number,
        cwa=wfo,
        time_zone="",
        fe_area="",
        name=_decode_string(values.get("NAME", b"")),
        state_zone=f"{prefix}{zone_number}",
        longitude=_decode_float(values.get("LON", b"")),
        latitude=_decode_float(values.get("LAT", b"")),
        short_name="",
    )


def iter_zone_records(path: str | Path) -> Iterator[ZoneRecord]:
    """Yield :class:`ZoneRecord` instances from a NOAA zone DBF.

    Supports both the public-forecast-zone schema (``z_*.dbf``) and the
    marine/Great-Lakes zone schema (``mz_*.dbf``). The two schemas have
    almost no columns in common; ``_detect_zone_schema`` picks the right
    parser. The yielded records share the same dataclass — marine
    entries simply leave ``time_zone``, ``fe_area``, and ``short_name``
    empty since the marine DBF doesn't carry them.
    """

    dbf_path = Path(path)
    with dbf_path.open("rb") as handle:
        header, fields = _read_header(handle)
        handle.seek(header.header_length)

        field_map: Dict[str, _DBFField] = {field.name.upper(): field for field in fields}
        schema = _detect_zone_schema(field_map)

        for _ in range(header.record_count):
            record_bytes = handle.read(header.record_length)
            if not record_bytes or len(record_bytes) < header.record_length:
                break
            if record_bytes[0] == 0x2A:  # Deleted marker
                continue
            offset = 1
            values: Dict[str, bytes] = {}
            for field in fields:
                field_data = record_bytes[offset : offset + field.length]
                offset += field.length
                values[field.name.upper()] = field_data

            if schema == "public":
                yield _parse_public_record(values)
            else:
                record = _parse_marine_record(values)
                if record is not None:
                    yield record


def detect_zone_schema(path: str | Path) -> str:
    """Return ``"public"`` or ``"marine"`` for ``path`` without parsing rows.

    Useful to callers that need to scope behaviour (e.g. delete-orphan
    logic) by schema without iterating the entire DBF.
    """

    dbf_path = Path(path)
    with dbf_path.open("rb") as handle:
        _, fields = _read_header(handle)
        field_map: Dict[str, _DBFField] = {field.name.upper(): field for field in fields}
        return _detect_zone_schema(field_map)


def iter_county_subdivision_records(path: str | Path) -> Iterator[CountySubdivisionRecord]:
    """Yield :class:`CountySubdivisionRecord` entries from a FEMA SAME DBF dump."""

    dbf_path = Path(path)
    with dbf_path.open("rb") as handle:
        header, fields = _read_header(handle)
        handle.seek(header.header_length)

        field_map: Dict[str, _DBFField] = {field.name.upper(): field for field in fields}
        required = [
            "STATE",
            "CWA",
            "COUNTYNAME",
            "FIPS",
            "TIME_ZONE",
            "FE_AREA",
            "LON",
            "LAT",
            "ENTIRESAME",
            "AREA_SAME",
            "AREA_NAME",
        ]
        missing = [name for name in required if name not in field_map]
        if missing:
            raise ValueError(
                f"DBF is missing required fields: {', '.join(missing)}"
            )

        for _ in range(header.record_count):
            record_bytes = handle.read(header.record_length)
            if not record_bytes or len(record_bytes) < header.record_length:
                break
            if record_bytes[0] == 0x2A:
                continue
            offset = 1
            values: Dict[str, bytes] = {}
            for field in fields:
                field_data = record_bytes[offset : offset + field.length]
                offset += field.length
                values[field.name.upper()] = field_data

            yield CountySubdivisionRecord(
                state_code=_decode_string(values["STATE"]).upper(),
                cwa=_decode_string(values["CWA"]).upper(),
                county_name=_decode_string(values["COUNTYNAME"]),
                fips=_decode_string(values["FIPS"]),
                time_zone=_decode_string(values["TIME_ZONE"]).upper(),
                fe_area=_decode_string(values["FE_AREA"]).upper(),
                longitude=_decode_float(values["LON"]),
                latitude=_decode_float(values["LAT"]),
                entire_same=_decode_string(values["ENTIRESAME"]),
                area_same=_decode_string(values["AREA_SAME"]),
                area_name=_decode_string(values["AREA_NAME"]),
            )


def load_zone_records(path: str | Path) -> List[ZoneRecord]:
    return list(iter_zone_records(path))


def _apply_to_model(model, record: ZoneRecord) -> bool:
    changed = False
    mapping = {
        "zone_code": record.zone_code,
        "state_code": record.state_code,
        "zone_number": record.zone_number,
        "zone_type": record.zone_type,
        "cwa": record.cwa,
        "time_zone": record.time_zone,
        "fe_area": record.fe_area,
        "name": record.name,
        "state_zone": record.state_zone,
        "longitude": record.longitude,
        "latitude": record.latitude,
        "short_name": record.short_name,
    }
    for attr, value in mapping.items():
        if getattr(model, attr) != value:
            setattr(model, attr, value)
            changed = True
    return changed


def sync_zone_catalog(
    session: Session,
    records: Sequence[ZoneRecord],
    *,
    commit: bool = True,
    source_path: str | Path | None = None,
    delete_scope: Union[str, bool, None] = None,
) -> ZoneSyncResult:
    """Synchronise ``nws_zones`` against ``records``.

    ``delete_scope`` controls which existing rows are eligible for the
    orphan-delete pass:

    * ``None`` (default): remove any existing zone whose ``zone_code`` is
      not in ``records``. Use this for a full reload from a single
      authoritative file (startup auto-load, the operator-triggered
      Reload button).
    * ``False``: never delete. Use this for additive uploads where the
      catalog is being assembled from multiple files (a marine ``mz``
      plus an offshore ``oz`` plus the public ``z`` all stack rather
      than overwriting each other). Inserts and updates still happen
      normally.
    * ``"public"``: only consider zones with two-letter U.S. state
      prefixes for removal. Marine rows are preserved.
    * ``"marine"``: only consider zones whose ``state_code`` matches a
      known marine UGC prefix for removal. Public zones are preserved.
      Note that this still wipes one marine file's zones when another
      marine file is loaded over it, which is why uploads use ``False``.
    """

    from app_core.models import NWSZone  # Imported lazily to avoid circular import

    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        # Ensure only one worker performs the catalog synchronisation at a time.
        session.execute(text("LOCK TABLE nws_zones IN SHARE ROW EXCLUSIVE MODE"))

    existing: Dict[str, NWSZone] = {
        zone.zone_code: zone for zone in session.query(NWSZone).all()
    }

    managed: Dict[str, NWSZone] = {}
    orphan_codes = set(existing.keys())
    updated_codes: set[str] = set()

    inserted = 0

    for record in records:
        zone = managed.get(record.zone_code)
        if zone is None:
            zone = existing.get(record.zone_code)
            if zone is None:
                zone = NWSZone()
                session.add(zone)
                inserted += 1
            else:
                orphan_codes.discard(record.zone_code)
            managed[record.zone_code] = zone

        if _apply_to_model(zone, record) and record.zone_code in existing:
            updated_codes.add(record.zone_code)

    updated = len(updated_codes)

    if delete_scope is False:
        # Caller wants a purely additive sync — never delete.
        orphan_codes = set()
    elif delete_scope is not None:
        try:
            from app_utils.fips_codes import MARINE_PREFIX_TO_SAME_STATE
        except Exception:
            MARINE_PREFIX_TO_SAME_STATE = {}
        marine_prefixes = set(MARINE_PREFIX_TO_SAME_STATE.keys())
        scoped: set[str] = set()
        for code in orphan_codes:
            zone_state = (existing[code].state_code or "").upper()
            is_marine = zone_state in marine_prefixes
            if delete_scope == "marine" and is_marine:
                scoped.add(code)
            elif delete_scope == "public" and not is_marine:
                scoped.add(code)
        orphan_codes = scoped

    removed = 0
    for zone_code in orphan_codes:
        session.delete(existing[zone_code])
        removed += 1

    if commit:
        try:
            session.commit()
        except Exception:
            session.rollback()
            raise

    resolved_path = Path(source_path) if source_path else Path(".")

    return ZoneSyncResult(
        source_path=resolved_path,
        total=len(records),
        inserted=inserted,
        updated=updated,
        removed=removed,
    )


__all__ = [
    "CountySubdivisionRecord",
    "ZoneRecord",
    "ZoneSyncResult",
    "iter_zone_records",
    "iter_county_subdivision_records",
    "load_zone_records",
    "sync_zone_catalog",
]
