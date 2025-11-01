from __future__ import annotations

from pathlib import Path

import pytest

from flask import Flask

from app_core.extensions import db
from app_core.models import NWSZone
from app_core.zones import (
    build_county_forecast_zone_map,
    clear_zone_lookup_cache,
    forecast_zones_for_same_code,
    format_zone_code_list,
    normalise_zone_codes,
    split_catalog_members,
)
from app_utils.zone_catalog import ZoneRecord, iter_zone_records, sync_zone_catalog


@pytest.fixture
def app_context(tmp_path):
    database_path = tmp_path / "zones.db"
    app = Flask("zone-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    clear_zone_lookup_cache()
    with app.app_context():
        engine = db.engine
        NWSZone.__table__.create(bind=engine)
        yield app
        db.session.remove()
        NWSZone.__table__.drop(bind=engine)
    clear_zone_lookup_cache()


def test_iter_zone_records_parses_catalog() -> None:
    record = next(iter_zone_records(Path("assets/z_05mr24.dbf")))
    assert record.zone_code == "ALZ019"
    assert record.name == "Calhoun"
    assert record.cwa == "BMX"
    assert pytest.approx(record.longitude, rel=1e-6) == -85.8261
    assert pytest.approx(record.latitude, rel=1e-6) == 33.7714


def test_sync_zone_catalog_upserts(app_context) -> None:
    first = ZoneRecord(
        zone_code="ALZ019",
        state_code="AL",
        zone_number="019",
        cwa="BMX",
        time_zone="C",
        fe_area="EC",
        name="Calhoun",
        state_zone="AL019",
        longitude=-85.8261,
        latitude=33.7714,
        short_name="Calhoun",
    )
    second = ZoneRecord(
        zone_code="ALZ046",
        state_code="AL",
        zone_number="046",
        cwa="BMX",
        time_zone="C",
        fe_area="SE",
        name="Bullock",
        state_zone="AL046",
        longitude=-85.7161,
        latitude=32.1005,
        short_name="Bullock",
    )

    result = sync_zone_catalog(db.session, [first, second], source_path="test.dbf")
    assert result.inserted == 2
    assert result.updated == 0
    assert result.removed == 0

    rows = NWSZone.query.order_by(NWSZone.zone_code).all()
    assert [row.zone_code for row in rows] == ["ALZ019", "ALZ046"]
    assert rows[0].name == "Calhoun"

    updated_first = ZoneRecord(
        zone_code="ALZ019",
        state_code="AL",
        zone_number="019",
        cwa="BMX",
        time_zone="C",
        fe_area="EC",
        name="Calhoun County",
        state_zone="AL019",
        longitude=-85.8261,
        latitude=33.7714,
        short_name="Calhoun",
    )

    result = sync_zone_catalog(db.session, [updated_first], source_path="test.dbf")
    assert result.inserted == 0
    assert result.updated == 1
    assert result.removed == 1

    stored = NWSZone.query.one()
    assert stored.zone_code == "ALZ019"
    assert stored.name == "Calhoun County"


def test_sync_zone_catalog_handles_duplicate_records(app_context) -> None:
    first = ZoneRecord(
        zone_code="ALZ019",
        state_code="AL",
        zone_number="019",
        cwa="BMX",
        time_zone="C",
        fe_area="EC",
        name="Calhoun",
        state_zone="AL019",
        longitude=-85.8261,
        latitude=33.7714,
        short_name="Calhoun",
    )
    duplicate = ZoneRecord(
        zone_code="ALZ019",
        state_code="AL",
        zone_number="019",
        cwa="BMX",
        time_zone="C",
        fe_area="EC",
        name="Calhoun County",
        state_zone="AL019",
        longitude=-85.8261,
        latitude=33.7714,
        short_name="Calhoun",
    )

    result = sync_zone_catalog(
        db.session, [first, duplicate], source_path="test.dbf"
    )
    assert result.inserted == 1
    assert result.updated == 0
    assert result.removed == 0

    stored = NWSZone.query.one()
    assert stored.zone_code == "ALZ019"
    assert stored.name == "Calhoun County"


def test_sync_zone_catalog_updates_once_for_duplicates(app_context) -> None:
    original = ZoneRecord(
        zone_code="ALZ019",
        state_code="AL",
        zone_number="019",
        cwa="BMX",
        time_zone="C",
        fe_area="EC",
        name="Calhoun",
        state_zone="AL019",
        longitude=-85.8261,
        latitude=33.7714,
        short_name="Calhoun",
    )
    sync_zone_catalog(db.session, [original], source_path="test.dbf")

    duplicate_records = [
        ZoneRecord(
            zone_code="ALZ019",
            state_code="AL",
            zone_number="019",
            cwa="BMX",
            time_zone="C",
            fe_area="EC",
            name="Calhoun",
            state_zone="AL019",
            longitude=-85.8261,
            latitude=33.7714,
            short_name="Calhoun",
        ),
        ZoneRecord(
            zone_code="ALZ019",
            state_code="AL",
            zone_number="019",
            cwa="BMX",
            time_zone="C",
            fe_area="EC",
            name="Calhoun County",
            state_zone="AL019",
            longitude=-85.8261,
            latitude=33.7714,
            short_name="Calhoun",
        ),
    ]

    result = sync_zone_catalog(
        db.session, duplicate_records, source_path="test.dbf"
    )
    assert result.inserted == 0
    assert result.updated == 1
    assert result.removed == 0

    stored = NWSZone.query.one()
    assert stored.zone_code == "ALZ019"
    assert stored.name == "Calhoun County"


def test_zone_code_normalisation_and_lookup(app_context) -> None:
    record = ZoneRecord(
        zone_code="ALZ019",
        state_code="AL",
        zone_number="019",
        cwa="BMX",
        time_zone="C",
        fe_area="EC",
        name="Calhoun",
        state_zone="AL019",
        longitude=-85.8261,
        latitude=33.7714,
        short_name="Calhoun",
    )
    sync_zone_catalog(db.session, [record], source_path="test.dbf")

    codes, invalid = normalise_zone_codes([" al019 ", "ALZ019", "bad-code"])
    assert codes == ["ALZ019"]
    assert invalid == ["BADCODE"]

    known, unknown = split_catalog_members(["ALZ019", "OHC137"])
    assert known == ["ALZ019", "OHC137"]
    assert unknown == []

    formatted = format_zone_code_list(["ALZ019", "OHC137"])
    assert formatted[0].startswith("ALZ019 – Calhoun")
    assert formatted[1].startswith("OHC137 – Putnam County")


def test_forecast_zone_lookup_matches_county_names(app_context) -> None:
    with app_context.app_context():
        clear_zone_lookup_cache()
        zone = NWSZone(
            zone_code="OHZ025",
            state_code="OH",
            zone_number="025",
            zone_type="Z",
            cwa="IWX",
            time_zone="E",
            fe_area="WC",
            name="Allen",
            short_name="Allen",
            state_zone="OH025",
            longitude=-84.1057,
            latitude=40.7715,
        )
        db.session.add(zone)
        db.session.commit()
        clear_zone_lookup_cache()

        mapping = build_county_forecast_zone_map()
        assert mapping.get("039003") == ["OHZ025"]

        codes = forecast_zones_for_same_code("039003")
        assert codes == ["OHZ025"]
