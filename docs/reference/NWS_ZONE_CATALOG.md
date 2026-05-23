# NWS Zone Catalog (Public, Marine, Fire, Offshore)

The `nws_zones` database table is EAS Station's runtime catalog of every
NWS Universal Geographic Code (UGC) zone — **public forecast zones**,
**marine zones (coastal, Great Lakes, offshore)**, and **fire-weather
zones**. Unlike the static county FIPS table in `app_utils/fips_codes.py`,
this catalog is loaded from a NOAA shapefile at install time and **must be
refreshed by operators** as NWS revises its zone definitions (typically
1–4 times per year).

This document records:

1. The authoritative .gov sources for each zone family.
2. The DBF schema the loader expects.
3. Every supported mechanism for altering / refreshing the catalog
   (CLI, admin UI, environment override, asset auto-detect, manual upload).
4. Cache and validator behavior callers should be aware of.

## Why a separate catalog?

The 5-digit county FIPS codes in `app_utils/fips_codes.py` (`US_FIPS_LOOKUP`)
are stable enough to embed as a string literal — counties change once a
decade or so, and the embedded list documents its own deviations
(see `docs/reference/FIPS_DATA_SOURCES.md`).

UGC zones are different:

* They are revised on **NWS's** schedule, not Census's, and changes are
  pushed mid-vintage (e.g. WFO boundary adjustments, marine zone re-splits
  after coastal storm-surge studies, new fire-weather zones).
* The catalog totals **5,000+ entries** (≈4,100 land zones + ≈600 marine
  zones + fire-weather zones), most of which are not relevant to any one
  station's filtering needs but must all be resolvable when an alert is
  ingested.
* Marine zones use alphabetic UGC prefixes (`AMZ`, `ANZ`, `GMZ`, …) that
  cannot be expressed in the FIPS numeric grid — the underlying data model
  is fundamentally different.

So the project ships with a **bundled DBF snapshot** (`assets/z_*.dbf`) that
seeds the catalog on first boot, and exposes operator tooling to swap in a
newer snapshot whenever NWS publishes one.

## Authoritative data sources

All source files are published by NOAA / NWS as ESRI shapefiles
(zipped `.shp` + `.shx` + `.dbf` + `.prj`). EAS Station only needs the
`.dbf` attribute table; the geometry files are discarded after extraction.

| Zone family | NWS landing page | Filename pattern | UGC prefixes |
| --- | --- | --- | --- |
| Public forecast zones (land) | <https://www.weather.gov/gis/PublicZones> | `z_DDmmYY.zip` (e.g. `z_18mr25.zip`) | `<ST>Z###` for each US state/territory |
| Marine zones (coastal, lakes, offshore) | <https://www.weather.gov/gis/MarineZones> | `mzDDmmYY.zip` (e.g. `mz18mr25.zip`) | `AMZ`, `ANZ`, `GMZ`, `LCZ`, `LEZ`, `LHZ`, `LMZ`, `LOZ`, `LSZ`, `PHZ`, `PKZ`, `PMZ`, `PSZ`, `PZZ`, `SLZ` |
| Fire-weather zones | <https://www.weather.gov/gis/FireZones> | `fz_DDmmYY.zip` | `<ST>Z###` (overlap public-zone prefixes; FE_AREA distinguishes them) |
| NWR partial counties (subdivisions) | <https://www.weather.gov/gis/NWRPartialCounties> | `csDDmmYY.zip` | Not zones — feeds `app_utils/fips_codes.py:_load_county_subdivision_index` |
| Offshore / High Seas (info only, not loaded) | <https://www.weather.gov/marine/zone/zmaoff> | n/a | `ANZ8##`, `PZZ8##`, `GMZ8##` (already in marine DBF) |

Format and field reference (NWS Operations Manual / WSOM):

* **WSOM J-section** (zone format & UGC code construction):
  <https://www.weather.gov/directives/010/archive/pd01005012.pdf>
* **NWS Directive 10-1701** (county/zone updates procedure):
  <https://www.weather.gov/directives/010/index.php?direct=017>

## DBF schemas (consumed by `iter_zone_records`)

The public-zone (`z_*.dbf`) and marine-zone (`mz_*.dbf` / `oz_*.dbf`)
shapefiles use **different** DBF attribute schemas. The loader at
`app_utils/zone_catalog.py:iter_zone_records` detects which schema a
file uses by inspecting its column names (`_detect_zone_schema`) and
dispatches to the appropriate parser. Both schemas yield the same
`ZoneRecord` dataclass so downstream code is unchanged.

### Public-zone schema (`z_*.dbf`)

| DBF field | Type | Example | Mapped to `ZoneRecord` |
| --- | --- | --- | --- |
| `STATE` | C(2) | `OH` | `state_code` |
| `CWA` | C(3) | `CLE` | `cwa` |
| `TIME_ZONE` | C(2) | `E`, `C` | `time_zone` |
| `FE_AREA` | C(2) | `nw`, `cm` | `fe_area` |
| `ZONE` | C(3) | `001`, `144` | `zone_number` (zero-padded) |
| `NAME` | C(70) | `Erie` | `name` |
| `STATE_ZONE` | C(5) | `OH001` | `state_zone` |
| `LON` | F | `-83.4` | `longitude` |
| `LAT` | F | `40.7` | `latitude` |
| `SHORTNAME` | C(45) | abbreviated name | `short_name` |

The loader synthesizes the full UGC code as `f"{STATE}Z{ZONE}"`. Only
`STATE`, `ZONE`, and `NAME` are required; the others are now optional
and fall back to empty strings if absent.

### Marine-zone schema (`mz_*.dbf`, `oz_*.dbf`)

| DBF field | Type | Example | Mapped to `ZoneRecord` |
| --- | --- | --- | --- |
| `ID` | C(6) — coastal / C(50) — offshore | `GMZ650` | `zone_code` (full UGC); first 2 chars → `state_code` (the alphabetic prefix); chars 3+ → `zone_number` |
| `WFO` | C(3) | `MOB` | `cwa` |
| `GL_WFO` | C(3) — coastal only | (Great Lakes WFO, usually blank) | preferred over `WFO` when populated |
| `NAME` | C(254) / C(90) | `Coastal waters from Pensacola FL to Pascagoula MS out 20 NM` | `name` |
| `LON`, `LAT` | F | `-87.5`, `30.3` | `longitude`, `latitude` |

The marine schema does not carry `TIME_ZONE`, `FE_AREA`, `SHORTNAME`,
or `STATE_ZONE`; those fields are left empty on the resulting
`ZoneRecord`. The two-letter `state_code` (e.g. `GM`, `AM`, `PH`,
`PK`) is what `app_utils/fips_codes.py:get_marine_state_tree` filters
on to surface marine areas in the admin FIPS picker.

### Fire-weather schema (`fz_*.dbf`)

Fire-weather DBFs use the public-zone schema, so the parser handles
them via the same `_parse_public_record` path. However, fire-weather
zone codes structurally overlap public-zone codes (`OHZ089` exists in
both files referring to different geographies), and the `nws_zones`
table currently enforces a unique constraint on `zone_code` alone.
Loading both `z_*.dbf` and `fz_*.dbf` therefore raises a duplicate-key
error mid-sync. Adding first-class fire-weather support requires
extending the schema to include `zone_type` in the uniqueness
constraint and is tracked as a known limitation.

### Schema detection errors

If a DBF doesn't match either schema, `_detect_zone_schema` raises
`ValueError("Unrecognised zone DBF schema. Expected …")` listing the
actual columns it found, so operators see a clear actionable error
before bad data lands in the database.

## Refresh mechanisms — how operators alter the catalog

The catalog supports **five** independent ways to be replaced or extended.
Pick whichever fits your deployment environment.

### 1. CLI — recommended for headless / CI / containerized installs

```bash
# Fetch the latest public, marine, and partial-county shapefiles into assets/
python tools/download_nws_gis_data.py

# Or fetch one family at a time:
python tools/download_nws_gis_data.py --zones      # public forecast zones
python tools/download_nws_gis_data.py --marine     # marine / coastal / lakes
python tools/download_nws_gis_data.py --partial    # NWR partial-county subdivisions

# Show the resolved download URLs without fetching (useful for air-gapped sites):
python tools/download_nws_gis_data.py --dry-run

# Apply the downloaded DBF(s) to the database:
python tools/sync_zone_catalog.py
python tools/sync_zone_catalog.py --dbf-path assets/mz18mr25.dbf   # explicit
```

The downloader scrapes each NWS landing page for the current ZIP filename
(date-stamped, e.g. `z_18mr25.zip` = 18-Mar-2025). If scraping fails it
falls back to a hard-coded URL (`_ZONE_FALLBACK`, `_MARINE_FALLBACK`,
`_PARTIAL_FALLBACK` in `tools/download_nws_gis_data.py`); update those
constants when NOAA publishes a new vintage and the previous-vintage URL
returns 404.

For supply-chain safety the downloader will only fetch from
`https://www.weather.gov/` — see `_ALLOWED_HOST` in the same file.

### 2. Admin UI upload — for interactive / single-host deployments

`/admin/zones` exposes:

* **Upload** (`POST /admin/zones/upload`): accepts a `.dbf` file, saves
  it under `assets/`, and immediately re-syncs. Implemented in
  `webapp/admin/zones.py:upload_zone_file`.
* **Reload** (`POST /admin/zones/reload`): re-syncs from whatever DBF
  the resolver currently picks up.
* **Info** (`GET /admin/zones/info`): reports the active path, file size,
  DBF record count, DB row count, and in-memory cache size.

Both endpoints require the `system.configure` permission.

### 3. Environment variable override

```bash
export NWS_ZONE_DBF_PATH=/srv/eas-station/zones/mz18mr25.dbf
```

When set, `_resolve_zone_catalog_path` (in `app_core/zones.py` and
`webapp/admin/zones.py`) prefers this path over auto-detection. Useful
for read-only container images that mount their zone catalog as a volume.

### 4. Asset auto-detect (default)

If neither an explicit path nor `NWS_ZONE_DBF_PATH` is provided, the
resolver picks the **lexicographically newest** `*.dbf` in `assets/`
(`sorted(..., reverse=True)`). The NWS naming convention `XXddmmyy.dbf`
sorts chronologically in *most* cases but **not all** — e.g.
`z_18mr25.dbf` sorts after `z_03ja25.dbf` only because `m` > `j`, which
is coincidental, not by design. When two vintages are installed
side-by-side, prefer the explicit `NWS_ZONE_DBF_PATH` mechanism.

To clean up older vintages automatically, the downloader removes any stale
file with the same prefix when it installs a new one
(see `_download_and_install` ≈ line 200).

### 5. Manual `assets/` drop

Drop a fresh `.dbf` into `assets/` and either:

* Restart the application (cold path: `ensure_zone_catalog` runs at boot).
* Hit `POST /admin/zones/reload` (warm path: just clears the cache and
  re-syncs).

## Cache & invalidation

The in-memory zone lookup is cached in `app_core/zones._ZONE_LOOKUP_CACHE`
(plus a derived forecast-zone-name index). Anything that mutates the
`nws_zones` table **must** call `clear_zone_lookup_cache()` afterward, or
`get_zone_lookup()` / `get_zone_info()` will return stale data until the
process restarts. Both `ensure_zone_catalog` and the admin reload/upload
routes already do this for you.

## Validator behavior

`normalise_zone_codes(values)` (in `app_core/zones.py`) is the single
choke point that user-supplied zone codes pass through (admin UI, API,
config files). It:

* Uppercases and strips whitespace + hyphens.
* Inserts the `Z` separator if the operator typed a 5-character form
  like `OH001` (becomes `OHZ001`).
* Returns `(valid_codes, invalid_tokens)`. The `invalid` list contains
  anything that doesn't match `^[A-Z]{2}Z\d{3}$`, **regardless of
  whether the catalog actually contains it.**

A second pass (`split_catalog_members`) splits the `valid` list into
`(known, unknown)` against the loaded catalog. `unknown` codes are kept —
they are not rejected — so that operators can pre-configure marine codes
*before* uploading the marine DBF, and so that brand-new NWS zones are
not silently dropped while waiting for the next catalog sync. The admin
UI surfaces the `unknown` set as a warning (see
`app_core/alert_filtering.py:181-200`).

## Marine zones — current operational state

| Question | Answer |
| --- | --- |
| Are marine waterway codes valid as `zone_codes` filter input today? | **Yes.** The validator accepts any well-formed `XXZ###` token. |
| Do they have human-readable names by default? | **Only if** an `mz_*.dbf` has been loaded. The shipped `assets/z_18mr25.dbf` contains land zones only (4,114 records, 0 marine). Without an `mz_*.dbf`, marine codes display as their bare UGC (e.g. `AMZ135`) rather than `Pamlico Sound`. |
| How do I add marine names? | Run `python tools/download_nws_gis_data.py --marine` then `python tools/sync_zone_catalog.py --dbf-path assets/mz*.dbf`, **or** upload the DBF via `/admin/zones`. |
| Does the existing `zone_codes` / `storage_zone_codes` filter pipeline handle marine? | **Yes** — `cap_poller.py:734-779` treats them identically to land zones; the alert match is purely a string-set membership test against the alert's `<geocode>` SAME/UGC blocks. |

## Related documentation

* `docs/reference/FIPS_DATA_SOURCES.md` — the static county FIPS table
  (the *other* half of EAS targeting data).
* `docs/reference/NRSC4B_SAME_STANDARD.md` — protocol-level format of the
  SAME location codes that ride in the EAS preamble.
* `docs/reference/NWS_ALERT_PARAMETERS.md` — the CAP ↔ EAS field mapping
  that consumes both the FIPS table and this zone catalog.
