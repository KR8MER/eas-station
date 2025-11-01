from __future__ import annotations

import pytest
from flask import Flask

from app_core.extensions import db
from app_core.location import describe_location_reference
from app_core.models import NWSZone
from app_core.zones import clear_zone_lookup_cache


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
        clear_zone_lookup_cache()
        yield app
        db.session.remove()
        NWSZone.__table__.drop(bind=engine)
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
