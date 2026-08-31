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

"""Regression test: app_core.cache.init_cache() must resolve on Flask-Caching
2.5+.

Flask-Caching 2.5.0 dropped its lowercase CACHE_TYPE aliases ('redis',
'simple', 'filesystem', 'null'). Cache._set_cache() builds an import path as
"flask_caching.backends." + CACHE_TYPE and imports it -- the backends
package used to expose those lowercase names as submodules/attributes, but
2.5+ only exposes the actual class names (RedisCache, SimpleCache,
FileSystemCache, NullCache). Passing the old lowercase value straight
through raised, at app startup:

    ImportError: module 'flask_caching.backends' has no attribute 'redis'

which crashed the whole web service (init_cache() runs unconditionally
during app creation), not just a cache miss. init_cache() now translates the
lowercase alias to the class name right at the Flask-Caching boundary,
keeping the lowercase form everywhere else (the CACHE_TYPE env var, the
Settings -> Environment dropdown, and already-deployed .env files all still
use 'redis'/'simple'/'filesystem').
"""

import os
from unittest.mock import patch

import pytest
from flask import Flask

from app_core.cache import init_cache


@pytest.fixture(autouse=True)
def _clean_cache_env(monkeypatch):
    for key in ("CACHE_TYPE", "CACHE_DIR", "CACHE_REDIS_URL"):
        monkeypatch.delenv(key, raising=False)


def _make_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


class TestCacheTypeResolvesOnFlaskCaching:
    def test_redis_alias_resolves_to_a_real_backend_class(self, monkeypatch):
        """Whether Redis is reachable or not, init_cache() must not crash --
        it either resolves RedisCache or falls back to SimpleCache, and
        either resolution must actually succeed against the installed
        Flask-Caching version."""
        monkeypatch.setenv("CACHE_TYPE", "redis")
        app = _make_app()

        cache = init_cache(app)

        assert app.config["CACHE_TYPE"] in ("RedisCache", "SimpleCache")
        # cache.init_app() would have raised ImportError before reaching
        # here if the resolved class name didn't exist in this version of
        # flask_caching.backends.
        assert cache.cache is not None

    def test_simple_alias_resolves(self, monkeypatch):
        monkeypatch.setenv("CACHE_TYPE", "simple")
        app = _make_app()

        init_cache(app)

        assert app.config["CACHE_TYPE"] == "SimpleCache"

    def test_filesystem_alias_resolves(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CACHE_TYPE", "filesystem")
        monkeypatch.setenv("CACHE_DIR", str(tmp_path / "eas-station-cache"))
        app = _make_app()

        init_cache(app)

        assert app.config["CACHE_TYPE"] == "FileSystemCache"

    def test_default_cache_type_is_redis_alias(self, monkeypatch):
        """No CACHE_TYPE set at all -- init_cache()'s own documented default
        ('redis') must still resolve, same as the explicit-'redis' case."""
        app = _make_app()

        init_cache(app)

        assert app.config["CACHE_TYPE"] in ("RedisCache", "SimpleCache")

    def test_unrecognized_cache_type_passes_through_unchanged(self, monkeypatch):
        """A value already given as a resolvable Flask-Caching class name
        (not one of our known lowercase aliases) must not be mangled."""
        monkeypatch.setenv("CACHE_TYPE", "NullCache")
        app = _make_app()

        init_cache(app)

        assert app.config["CACHE_TYPE"] == "NullCache"
