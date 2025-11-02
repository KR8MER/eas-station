from __future__ import annotations

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app_core.extensions import db
from app_core.location import describe_location_reference, update_location_settings
from app_core.models import LocationSettings, NWSZone
from app_core.zones import clear_zone_lookup_cache
from app_utils.fips_codes import get_same_lookup, get_us_state_county_tree
from app_utils.location_settings import sanitize_fips_codes


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def app_context(tmp_path):
    database_path = tmp_path / "location.db"
    app = Flask("location-reference-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        engine = db.engine
        NWSZone.__table__.create(bind=engine)
        LocationSettings.__table__.create(bind=engine)
        clear_zone_lookup_cache()
        yield app
        db.session.remove()
        NWSZone.__table__.drop(bind=engine)
        LocationSettings.__table__.drop(bind=engine)
    clear_zone_lookup_cache()


def test_describe_location_reference_includes_zone_and_fips_details(app_context):
    with app_context.app_context():
        zone = NWSZone(
            zone_code="OHZ016",
            state_code="OH",
            zone_number="016",
            zone_type="Z",
            cwa="CLE",
            time_zone="E",
            fe_area="NE",
            name="Putnam",
            short_name="Putnam",
            state_zone="OH016",
            longitude=-84.119,
            latitude=40.86,
        )
        db.session.add(zone)
        db.session.commit()
        clear_zone_lookup_cache()

        settings = {
            "county_name": "Putnam County",
            "state_code": "OH",
            "timezone": "America/New_York",
            "fips_codes": ["039137"],
            "zone_codes": ["OHZ016", "OHC137"],
            "area_terms": ["PUTNAM COUNTY", "OTTAWA"],
        }

        snapshot = describe_location_reference(settings)

        assert snapshot["location"]["county_name"] == "Putnam County"
        assert snapshot["location"]["state_code"] == "OH"

        zones = snapshot["zones"]["known"]
        assert len(zones) == 2
        zone_lookup = {zone["code"]: zone for zone in zones}

        assert zone_lookup["OHZ016"]["cwa"] == "CLE"
        assert zone_lookup["OHZ016"]["label"].startswith("OHZ016")

        county_zone = zone_lookup["OHC137"]
        assert county_zone["zone_type"] == "C"
        assert county_zone["same_code"] == "039137"
        assert county_zone["fips_code"] == "39137"
        assert county_zone["state_fips"] == "39"
        assert county_zone["county_fips"] == "137"
        assert county_zone["label"].startswith("OHC137 – Putnam County")

        fips_entries = snapshot["fips"]["known"]
        assert len(fips_entries) == 1
        assert fips_entries[0]["code"] == "039137"
        assert fips_entries[0]["state"] == "OH"
        assert fips_entries[0]["county"].startswith("Putnam")
        assert not snapshot["fips"]["missing"]
        assert not snapshot["zones"]["missing"]

        assert snapshot["area_terms"] == ["PUTNAM COUNTY", "OTTAWA"]

        sources = snapshot.get("sources", [])
        assert any(item.get("path") == "assets/pd01005007curr.pdf" for item in sources)
        assert any(item.get("url") == "https://www.weather.gov/gis/PublicZones" for item in sources)


def test_update_location_settings_infers_county_zones(app_context):
    with app_context.app_context():
        clear_zone_lookup_cache()
        zone_allen = NWSZone(
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
        zone_putnam = NWSZone(
            zone_code="OHZ016",
            state_code="OH",
            zone_number="016",
            zone_type="Z",
            cwa="IWX",
            time_zone="E",
            fe_area="WC",
            name="Putnam",
            short_name="Putnam",
            state_zone="OH016",
            longitude=-84.1317,
            latitude=41.0221,
        )
        db.session.add_all([zone_allen, zone_putnam])
        db.session.commit()
        clear_zone_lookup_cache()

        result = update_location_settings(
            {
                "county_name": "Allen County",
                "state_code": "OH",
                "timezone": "America/New_York",
                "fips_codes": ["039003", "039137"],
                "zone_codes": [],
                "area_terms": ["ALLEN COUNTY"],
            }
        )

        assert "OHZ025" in result["zone_codes"]
        assert "OHZ016" in result["zone_codes"]
        assert "OHC003" in result["zone_codes"]
        assert "OHC137" in result["zone_codes"]
        assert result["zone_codes"].count("OHC137") == 1

        stored = LocationSettings.query.first()
        assert stored is not None
        assert "OHZ025" in stored.zone_codes
        assert "OHZ016" in stored.zone_codes
        assert "OHC003" in stored.zone_codes
        assert "OHC137" in stored.zone_codes


def test_update_location_settings_accepts_statewide_same_code(app_context):
    with app_context.app_context():
        clear_zone_lookup_cache()

        result = update_location_settings(
            {
                "county_name": "Putnam County",
                "state_code": "OH",
                "timezone": "America/New_York",
                "fips_codes": ["039000", "039137"],
                "zone_codes": [],
                "area_terms": [],
            }
        )

        assert "039000" in result["fips_codes"]

        stored = LocationSettings.query.first()
        assert stored is not None
        assert "039000" in stored.fips_codes

        snapshot = describe_location_reference(result)
        statewide_entry = {
            entry["code"]: entry for entry in snapshot["fips"]["known"]
        }.get("039000")

        assert statewide_entry is not None
        assert statewide_entry["is_statewide"]
        assert statewide_entry["state"] == "OH"
        assert statewide_entry["county"].startswith("Entire Ohio")


def test_sanitize_fips_codes_allows_statewide_entries():
    valid, invalid = sanitize_fips_codes(["039000", "039137", "039000", "bad-code"])

    assert valid == ["039000", "039137"]
    assert invalid == ["bad-code"]


def test_sanitize_fips_codes_allows_partial_counties():
    valid, invalid = sanitize_fips_codes(["627137", "bad", "039137"])

    assert "627137" in valid
    assert "039137" in valid
    assert "bad" in invalid


def test_state_tree_includes_county_subdivisions():
    tree = get_us_state_county_tree()
    mn = next((state for state in tree if state.get("abbr") == "MN"), None)
    assert mn is not None
    st_louis = next(
        (county for county in mn.get("counties", []) if county.get("code") == "027137"),
        None,
    )
    assert st_louis is not None
    subdivisions = [sub.get("code") for sub in st_louis.get("subdivisions", [])]
    assert "627137" in subdivisions


def test_same_lookup_contains_partial_counties():
    lookup = get_same_lookup()
    label = lookup.get("627137")
    assert label is not None
    assert "St. Louis" in label


def test_describe_location_reference_flags_unknown_zones(app_context):
    with app_context.app_context():
        clear_zone_lookup_cache()

        settings = {
            "county_name": "Example County",
            "state_code": "TX",
            "timezone": "America/Chicago",
            "fips_codes": ["039137"],
            "zone_codes": ["TXZ999"],
            "area_terms": ["EXAMPLE"],
        }

        snapshot = describe_location_reference(settings)

        assert "TXZ999" in snapshot["zones"]["missing"]
        assert snapshot["fips"]["known"]
        assert not snapshot["fips"]["missing"]
        assert snapshot["area_terms"] == ["EXAMPLE"]

        sources = snapshot.get("sources", [])
        assert any(item.get("path") == "assets/pd01005007curr.pdf" for item in sources)
        assert any(item.get("url") == "https://www.weather.gov/gis/PublicZones" for item in sources)
