"""Utilities for working with the NOAA public forecast zone catalog."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

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


def iter_zone_records(path: str | Path) -> Iterator[ZoneRecord]:
    """Yield :class:`ZoneRecord` instances from the provided DBF file."""

    dbf_path = Path(path)
    with dbf_path.open("rb") as handle:
        header, fields = _read_header(handle)
        handle.seek(header.header_length)

        field_map: Dict[str, _DBFField] = {field.name.upper(): field for field in fields}
        required = [
            "STATE",
            "CWA",
            "TIME_ZONE",
            "FE_AREA",
            "ZONE",
            "NAME",
            "STATE_ZONE",
            "LON",
            "LAT",
            "SHORTNAME",
        ]
        missing = [name for name in required if name not in field_map]
        if missing:
            raise ValueError(f"DBF is missing required fields: {', '.join(missing)}")

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

            state = _decode_string(values["STATE"]).upper()
            zone_number = _normalise_zone_number(_decode_string(values["ZONE"]))
            zone_code = f"{state}Z{zone_number}" if state else zone_number

            yield ZoneRecord(
                zone_code=zone_code,
                state_code=state,
                zone_number=zone_number,
                cwa=_decode_string(values["CWA"]).upper(),
                time_zone=_decode_string(values["TIME_ZONE"]).upper(),
                fe_area=_decode_string(values["FE_AREA"]).upper(),
                name=_decode_string(values["NAME"]),
                state_zone=_decode_string(values["STATE_ZONE"]).upper(),
                longitude=_decode_float(values["LON"]),
                latitude=_decode_float(values["LAT"]),
                short_name=_decode_string(values["SHORTNAME"]),
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
) -> ZoneSyncResult:
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
    "ZoneRecord",
    "ZoneSyncResult",
    "iter_zone_records",
    "load_zone_records",
    "sync_zone_catalog",
]
