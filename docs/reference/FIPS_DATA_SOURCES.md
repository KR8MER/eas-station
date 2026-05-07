# FIPS / SAME Location Code Data Sources

The county and SAME location codes baked into `app_utils/fips_codes.py`
(`US_FIPS_COUNTY_TABLE`, `COUNTY_SUBDIVISIONS`, `US_FIPS_LOOKUP`) are derived
from authoritative U.S. Government sources. This document records those
sources so the table can be regenerated or audited as the underlying
geographies change (Connecticut planning regions, Alaska borough splits,
new municipios, etc.).

## Authoritative U.S. Government sources

### 1. SAME / EAS location codes — NOAA / National Weather Service

The canonical, EAS-operational list of SAME (Specific Area Message Encoding)
location codes is published by the National Weather Service. It includes
every county/parish/borough plus the marine and offshore Z-zones that
NWR/EAS receivers can decode.

| Source | URL | Notes |
| --- | --- | --- |
| NWR SAME index (HTML, browseable by state) | <https://www.weather.gov/nwr/counties> | Human-readable master index. |
| Per-state SAME tables (plain text) | `https://www.weather.gov/nwr/SAMECountyTextFiles/<XX>SAME.txt` (e.g. `OHSAME.txt`) | Authoritative text format used by station engineers. |
| NWS public-zone shapefiles | <https://www.weather.gov/gis/PublicZones> | County / zone boundaries with the SAME/UGC code as an attribute. |

`47 CFR § 11.31` (FCC Part 11) defines the **format** of the SAME location
code (`PSSCCC`, with leading portion digit `P`) but defers to the U.S.
Census Bureau for the underlying SS+CCC values.

* eCFR Part 11: <https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-11>

### 2. County FIPS / ANSI codes — U.S. Census Bureau

The 5-digit county FIPS values in `US_FIPS_COUNTY_TABLE` come from the
Census Bureau, which maintains the list as ANSI INCITS 31. NIST's original
FIPS PUB 6-4 was withdrawn in 2008 and Census is now the official keeper.

| Source | URL | Notes |
| --- | --- | --- |
| `national_county.txt` (current vintage) | <https://www2.census.gov/geo/docs/reference/codes/files/national_county.txt> | One row per county; pipe-delimited `STATE|STATEFP|COUNTYFP|COUNTYNAME|CLASSFP`. |
| `national_county2020.txt` (2020 vintage) | <https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt> | Includes the 2022 Connecticut planning-region restructuring and Alaska's 2008/2013/2015 reorganizations. |
| Gazetteer files (centroids, ANSI) | <https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html> | Adds latitude/longitude and ANSI codes for cross-reference. |

The territory entries (PR, USVI, Guam, American Samoa, CNMI) live in the
same `national_county.txt` file; the freely-associated states (FSM 64,
RMI 68, Palau 70) are not U.S. territory and are intentionally omitted.

### 3. County subdivisions — U.S. Census Bureau

The optional subdivisions surfaced through `COUNTY_SUBDIVISIONS` /
`US_FIPS_SUBDIVISIONS` come from the Census Bureau's MCD (minor civil
division) Gazetteer file:

* <https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html>
  (the `*_gazetteer_county_subdivision.txt` artifact)

These map to SAME portion digits 1-9 via the `P` digit defined in
47 CFR § 11.31 and `P_DIGIT_LABELS` in `app_utils/fips_codes.py`.

## Regenerating the embedded table

`US_FIPS_COUNTY_TABLE` is intentionally embedded as a literal string so the
package has no runtime dependency on a network fetch or shipped data file.
To refresh it:

1. Download the current `national_county.txt` from Census (link above).
2. Drop rows for the freely-associated states (FIPS state codes 64, 68, 70)
   and any non-SAME entries.
3. Reformat each row as `STATEFP+COUNTYFP|ST|County Name` (e.g.
   `29183|MO|St. Charles County`). Preserve diacritics where Census uses
   them (e.g. `Bayamón`, `Doña Ana`, `Mayagüez`).
4. Cross-check the resulting set against the relevant per-state NWS
   `*SAME.txt` files; any code present in both must match.
5. Run the FIPS-related tests
   (`pytest tests/test_eas_monitor_fips_matching.py
   tests/test_detect_county_wide_false_positive.py
   tests/test_audio_detail_locations.py`) before committing.

## Known intentional deviations

* **DC (`11001`)** is labeled `District of Columbia` in this repo for clarity,
  whereas Census labels the county `Washington` (the District itself is the
  parent state). The NWS SAME list also uses *District of Columbia*, which we
  follow.
* **Alaska**: this repo carries the post-2013/2015/2019 borough/census-area
  splits (Hoonah-Angoon `02105`, Kusilvak `02158`, Petersburg `02195`,
  Prince of Wales-Hyder `02198`, Skagway `02230`, Wrangell `02275`) and
  omits the retired predecessors (`02201`, `02232`, `02270`, `02280`).
* **South Dakota**: `46102` *Oglala Lakota County* is included instead of
  the renamed `46113` *Shannon County* (renamed by SD legislature in 2015).
* **Marine / offshore Z-zones** from the NWS list (e.g. `LE…`, `PZ…`) are
  *not* included — `app_utils/fips_codes.py` covers only land-area FIPS
  codes. EAS receivers handle marine zones through a separate UGC zone
  table.
