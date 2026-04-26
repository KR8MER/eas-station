"""Tests for boundary GeoJSON / shapefile upload helpers and endpoints.

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

import importlib.util
import io
import sys
import types
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


pyshp = pytest.importorskip("shapefile", reason="pyshp required for shapefile tests")


def _load_boundaries_module():
    """Load webapp/admin/boundaries.py directly, bypassing webapp/__init__.py.

    The full webapp package eagerly imports audio/SDR/Zigbee modules whose
    optional native dependencies are not installed in the test environment.
    Loading the file in isolation lets us exercise the boundary helpers and
    the blueprint without dragging in those unrelated subsystems.
    """
    cached = sys.modules.get("_boundaries_under_test")
    if cached is not None:
        return cached

    # Provide stub parents so the spec-based loader is happy when registering.
    if "webapp" not in sys.modules:
        sys.modules["webapp"] = types.ModuleType("webapp")
    if "webapp.admin" not in sys.modules:
        admin_pkg = types.ModuleType("webapp.admin")
        admin_pkg.__path__ = []  # mark as package
        sys.modules["webapp.admin"] = admin_pkg

    src = PROJECT_ROOT / "webapp" / "admin" / "boundaries.py"
    spec = importlib.util.spec_from_file_location(
        "_boundaries_under_test", str(src)
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_boundaries_under_test"] = module
    spec.loader.exec_module(module)
    return module


boundaries = _load_boundaries_module()


# Web Mercator (EPSG:3857) WKT used to verify reprojection to WGS84.
WEB_MERCATOR_WKT = (
    'PROJCS["WGS 84 / Pseudo-Mercator",'
    'GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
    'PROJECTION["Mercator_1SP"],'
    'PARAMETER["central_meridian",0],'
    'PARAMETER["scale_factor",1],'
    'PARAMETER["false_easting",0],'
    'PARAMETER["false_northing",0],'
    'UNIT["metre",1],AUTHORITY["EPSG","3857"]]'
)


def _write_polygon_shapefile(directory: Path, basename: str, ring, prj_wkt=None):
    """Write a one-feature polygon shapefile and return the .shp path."""
    base = directory / basename
    writer = pyshp.Writer(str(base), shapeType=pyshp.POLYGON)
    writer.field("NAME", "C", size=50)
    writer.poly([ring])
    writer.record("Test Boundary")
    writer.close()
    if prj_wkt is not None:
        (directory / f"{basename}.prj").write_text(prj_wkt, encoding="utf-8")
    return base.with_suffix(".shp")


def _zip_shapefile(shp_path: Path) -> bytes:
    """Bundle the .shp + companions into an in-memory ZIP archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            companion = shp_path.with_suffix(ext)
            if companion.exists():
                zf.write(companion, arcname=companion.name)
    buf.seek(0)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Pure helper tests - no Flask, no DB required
# ---------------------------------------------------------------------------


class TestConvertShapefileToGeoJSON:
    def test_converts_simple_polygon_without_prj(self, tmp_path):
        convert_shapefile_to_geojson = boundaries.convert_shapefile_to_geojson

        ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
        shp = _write_polygon_shapefile(tmp_path, "no_prj", ring)

        gj = convert_shapefile_to_geojson(str(shp))

        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) == 1
        feature = gj["features"][0]
        assert feature["geometry"]["type"] == "Polygon"
        assert feature["properties"]["NAME"] == "Test Boundary"
        # Without a .prj, coordinates are unchanged.
        assert feature["geometry"]["coordinates"][0][0] == [0.0, 0.0] or \
            tuple(feature["geometry"]["coordinates"][0][0]) == (0.0, 0.0)

    def test_reprojects_when_prj_present(self, tmp_path):
        pytest.importorskip("pyproj", reason="pyproj required for reprojection")
        convert_shapefile_to_geojson = boundaries.convert_shapefile_to_geojson

        # Roughly 1 km square near the equator/prime meridian, in Web Mercator metres.
        ring = [
            (1000.0, 1000.0),
            (1000.0, 2000.0),
            (2000.0, 2000.0),
            (2000.0, 1000.0),
            (1000.0, 1000.0),
        ]
        shp = _write_polygon_shapefile(
            tmp_path, "mercator", ring, prj_wkt=WEB_MERCATOR_WKT
        )

        gj = convert_shapefile_to_geojson(str(shp))
        coords = gj["features"][0]["geometry"]["coordinates"][0]

        # After reprojection, coordinates should be near 0,0 in degrees.
        for x, y in (coords[i][:2] for i in range(len(coords))):
            assert -1.0 < x < 1.0
            assert -1.0 < y < 1.0

    def test_passthrough_when_prj_already_wgs84(self, tmp_path):
        pytest.importorskip("pyproj", reason="pyproj required")
        convert_shapefile_to_geojson = boundaries.convert_shapefile_to_geojson

        wgs84_wkt = (
            'GEOGCS["WGS 84",DATUM["WGS_1984",'
            'SPHEROID["WGS 84",6378137,298.257223563]],'
            'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],'
            'AUTHORITY["EPSG","4326"]]'
        )
        ring = [(10.0, 20.0), (10.0, 21.0), (11.0, 21.0), (11.0, 20.0), (10.0, 20.0)]
        shp = _write_polygon_shapefile(tmp_path, "wgs84", ring, prj_wkt=wgs84_wkt)

        gj = convert_shapefile_to_geojson(str(shp))
        first = gj["features"][0]["geometry"]["coordinates"][0][0]
        # Same numeric values, no reprojection.
        assert tuple(first[:2]) == (10.0, 20.0)


class TestReadPrjWkt:
    def test_returns_none_without_prj(self, tmp_path):
        _read_prj_wkt = boundaries._read_prj_wkt

        shp = tmp_path / "missing.shp"
        shp.write_bytes(b"")
        assert _read_prj_wkt(str(shp)) is None

    def test_reads_prj_contents(self, tmp_path):
        _read_prj_wkt = boundaries._read_prj_wkt

        shp = tmp_path / "x.shp"
        shp.write_bytes(b"")
        (tmp_path / "x.prj").write_text(WEB_MERCATOR_WKT, encoding="utf-8")
        wkt = _read_prj_wkt(str(shp))
        assert wkt is not None and "Pseudo-Mercator" in wkt


class TestBuildReprojector:
    def test_returns_none_when_no_prj(self):
        _build_reprojector = boundaries._build_reprojector

        assert _build_reprojector(None) is None

    def test_returns_none_for_unparseable_prj(self):
        _build_reprojector = boundaries._build_reprojector

        assert _build_reprojector("not-a-wkt-string") is None

    def test_returns_none_when_already_wgs84(self):
        pytest.importorskip("pyproj")
        _build_reprojector = boundaries._build_reprojector

        wgs84_wkt = (
            'GEOGCS["WGS 84",DATUM["WGS_1984",'
            'SPHEROID["WGS 84",6378137,298.257223563]],'
            'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],'
            'AUTHORITY["EPSG","4326"]]'
        )
        assert _build_reprojector(wgs84_wkt) is None


class TestReprojectGeometry:
    def test_passthrough_when_transform_is_none(self):
        _reproject_geometry = boundaries._reproject_geometry

        geom = {"type": "Point", "coordinates": [1.0, 2.0]}
        assert _reproject_geometry(geom, None) is geom

    def test_polygon_recursion(self):
        _reproject_geometry = boundaries._reproject_geometry

        def transform(x, y):
            return (x + 10, y + 20)

        geom = {
            "type": "Polygon",
            "coordinates": [[(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)]],
        }
        out = _reproject_geometry(geom, transform)
        assert out["coordinates"][0][0] == [10, 20]
        assert out["coordinates"][0][2] == [11, 21]

    def test_multipolygon_recursion(self):
        _reproject_geometry = boundaries._reproject_geometry

        def transform(x, y):
            return (x * 2, y * 3)

        geom = {
            "type": "MultiPolygon",
            "coordinates": [
                [[(0, 0), (0, 1), (1, 0), (0, 0)]],
                [[(5, 5), (5, 6), (6, 5), (5, 5)]],
            ],
        }
        out = _reproject_geometry(geom, transform)
        assert out["coordinates"][0][0][1] == [0, 3]
        assert out["coordinates"][1][0][1] == [10, 18]

    def test_preserves_z_coordinate(self):
        _reproject_geometry = boundaries._reproject_geometry

        def transform(x, y):
            return (x + 1, y + 1)

        geom = {"type": "Point", "coordinates": [0.0, 0.0, 42.0]}
        out = _reproject_geometry(geom, transform)
        assert out["coordinates"] == [1.0, 1.0, 42.0]


class TestGetShapefileDirectory:
    def test_env_override_takes_precedence(self, tmp_path, monkeypatch):
        get_shapefile_directory = boundaries.get_shapefile_directory

        monkeypatch.setenv("EAS_SHAPEFILE_DIR", str(tmp_path))
        assert get_shapefile_directory() == tmp_path

    def test_falls_back_to_default_when_env_unset(self, monkeypatch):
        get_shapefile_directory = boundaries.get_shapefile_directory

        monkeypatch.delenv("EAS_SHAPEFILE_DIR", raising=False)
        result = get_shapefile_directory()
        # Should resolve to a path under the project root, not the legacy
        # absolute /home/user/eas-station/streams\ and\ ponds string.
        assert isinstance(result, Path)
        assert result.is_absolute()


# ---------------------------------------------------------------------------
# HTTP-level tests - exercise blueprint routing without a real database
# ---------------------------------------------------------------------------


def _make_test_app():
    """Build a minimal Flask app with the boundaries blueprint registered."""
    from flask import Flask
    boundaries_bp = boundaries.boundaries_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(boundaries_bp)
    return app


class TestUploadShapefileEndpoint:
    def test_rejects_missing_file(self):
        app = _make_test_app()
        client = app.test_client()
        resp = client.post(
            "/admin/upload_shapefile",
            data={"boundary_type": "rivers"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "file upload or shapefile_path" in resp.get_json()["error"]

    def test_rejects_bare_shp_with_friendly_message(self):
        app = _make_test_app()
        client = app.test_client()
        resp = client.post(
            "/admin/upload_shapefile",
            data={
                "boundary_type": "rivers",
                "file": (io.BytesIO(b"\x00" * 10), "boundaries.shp"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        msg = resp.get_json()["error"]
        assert "companion" in msg.lower()
        assert "zip" in msg.lower()

    def test_rejects_unsupported_extension(self):
        app = _make_test_app()
        client = app.test_client()
        resp = client.post(
            "/admin/upload_shapefile",
            data={
                "boundary_type": "rivers",
                "file": (io.BytesIO(b"hello"), "boundaries.txt"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "ZIP archive" in resp.get_json()["error"]

    def test_zip_without_shp_returns_error(self):
        app = _make_test_app()
        client = app.test_client()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "no shapefile here")
        buf.seek(0)

        resp = client.post(
            "/admin/upload_shapefile",
            data={
                "boundary_type": "rivers",
                "file": (buf, "empty.zip"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "No .shp file" in resp.get_json()["error"]

    def test_valid_zip_invokes_db_insertion(self, tmp_path):
        """End-to-end: ZIP -> conversion -> ORM rows added (DB mocked)."""
        app = _make_test_app()

        ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
        shp = _write_polygon_shapefile(tmp_path, "rivers", ring)
        zip_bytes = _zip_shapefile(shp)

        added = []

        class FakeSession:
            def execute(self, *_args, **_kwargs):
                class _Result:
                    def scalar(self_inner):
                        return "POSTGIS_GEOMETRY_PLACEHOLDER"
                return _Result()

            def add(self, obj):
                added.append(obj)

            def commit(self):
                pass

            def rollback(self):
                pass

        with patch.object(boundaries, "db") as mock_db:
            mock_db.session = FakeSession()
            client = app.test_client()
            resp = client.post(
                "/admin/upload_shapefile",
                data={
                    "boundary_type": "rivers",
                    "file": (io.BytesIO(zip_bytes), "rivers.zip"),
                },
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["boundaries_added"] == 1
        assert body["total_features"] == 1
        assert len(added) == 1


class TestUploadBoundariesEndpoint:
    def test_rejects_missing_file(self):
        app = _make_test_app()
        client = app.test_client()
        resp = client.post(
            "/admin/upload_boundaries",
            data={"boundary_type": "rivers"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "No file provided"

    def test_rejects_non_geojson_extension(self):
        app = _make_test_app()
        client = app.test_client()
        resp = client.post(
            "/admin/upload_boundaries",
            data={
                "boundary_type": "rivers",
                "file": (io.BytesIO(b"{}"), "data.csv"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "GeoJSON" in resp.get_json()["error"]

    def test_rejects_invalid_json(self):
        app = _make_test_app()
        client = app.test_client()
        resp = client.post(
            "/admin/upload_boundaries",
            data={
                "boundary_type": "rivers",
                "file": (io.BytesIO(b"not json {"), "data.geojson"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "Invalid GeoJSON" in resp.get_json()["error"]


class TestListShapefilesEndpoint:
    def test_returns_empty_when_dir_missing(self, tmp_path, monkeypatch):
        app = _make_test_app()
        monkeypatch.setenv("EAS_SHAPEFILE_DIR", str(tmp_path / "does_not_exist"))
        client = app.test_client()
        resp = client.get("/admin/list_shapefiles")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["shapefiles"] == []
        assert "not found" in body["message"].lower()

    def test_lists_companion_files(self, tmp_path, monkeypatch):
        app = _make_test_app()
        ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
        _write_polygon_shapefile(tmp_path, "streams", ring, prj_wkt=WEB_MERCATOR_WKT)

        monkeypatch.setenv("EAS_SHAPEFILE_DIR", str(tmp_path))
        client = app.test_client()
        resp = client.get("/admin/list_shapefiles")
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["shapefiles"]) == 1
        entry = body["shapefiles"][0]
        assert entry["filename"] == "streams.shp"
        assert entry["complete"] is True
        assert entry["has_shx"] is True
        assert entry["has_dbf"] is True
        assert entry["has_prj"] is True
        # Filename contains "stream" so suggested_type should be rivers.
        assert entry["suggested_type"] == "rivers"
