# Large File Refactor Plan

**Status:** In progress · **Started:** 2026-08-06

`docs/development/AGENTS.md` sets the size guidance for this repository:

> Aim to keep Python modules under ~400 lines and HTML templates under ~300 lines.
> When adding more than one new class or multiple functions to a module already
> above 350 lines, create or use a sibling module/package instead of expanding
> the existing file.

Today the tree violates that guidance in **131 Python modules**, **75 templates**
and **16 JavaScript files**. That number will not go to zero in one pass, and
trying would produce an unreviewable diff across the whole codebase. This
document is the running plan: it records the inventory, the extraction strategy
per file, and which phases have landed.

---

## Ground rules for every extraction

These are what make a split reviewable and safe. Follow them on every file.

1. **Move code verbatim.** A refactor commit changes *where* code lives, not what
   it does. Behavioural changes go in a separate commit, so a reviewer can read
   the split diff as pure motion.
2. **Keep the old import path working.** The original module becomes a shim that
   re-exports the public names from the new package. Nothing outside the
   refactored area should need to change in the same commit — `from
   app_core.radio.demodulation import FMDemodulator` must keep working.
3. **One seam per module.** Split along a real boundary (data vs. logic, DSP
   kernels vs. protocol decode, route handlers vs. helpers), never at an
   arbitrary line number just to get under the cap.
4. **Preserve `__all__` and the module docstring** on the shim so `help()` and
   star-imports behave as before.
5. **Run the tests that cover the file** before and after, and name them in the
   commit message. If a file has no coverage, that is worth knowing before it is
   moved.
6. **Follow the existing naming convention.** When a module is superseded, the
   old one is renamed with an `_old` suffix — never `_new` for the replacement.
   In practice most splits here need no rename because the original path stays
   as the shim.

The repository already has a worked example of this pattern:
`webapp/routes_audio_archive.py` (928 lines) became the `webapp/audio_archive/`
package — `fsutil.py`, `config.py`, `metadata.py`, `routes.py` — in 2.133.1.
New splits should look like that one.

---

## Phase 1 — Data/code separation ✅

The cheapest wins: modules that are mostly a static data table with a thin layer
of lookup logic wrapped around it. Nothing executable moves, so the risk is
close to zero and the line-count win is large.

| File | Before | After | Action |
| --- | ---: | ---: | --- |
| `app_utils/fips_codes.py` | 3887 | ~660 | ✅ 3,225-line `US_FIPS_COUNTY_TABLE` string literal moved to `app_utils/data/us_fips_counties.txt`, read at import |

**Landed in 2.134.0.** The table is FCC/Census reference data, not code —
keeping it inline meant every reader of the lookup helpers scrolled past 3,200
lines of county names, and every diff touching the module rendered them. The
data file keeps the identical `FIPS|ST|Name` pipe format, so it stays greppable
and diffable, and it is resolved relative to `__file__` the same way the module
already resolves the NWS partial-county `.dbf` from `assets/`. (The project is
deployed as a git checkout, not an installed wheel, so no `package_data` entry
is needed.)

### Remaining Phase 1 candidates

None found above 800 lines. `app_utils/event_codes.py` and
`app_utils/zone_catalog.py` carry data tables but are already under the cap.

---

## Phase 2 — Signal-processing and rendering packages

Large single-purpose modules with clean internal seams. These are pure library
code with no Flask involvement, which makes them the safest of the big splits.

| File | Lines | Planned layout | Status |
| --- | ---: | --- | --- |
| `app_core/radio/demodulation.py` | 5355 | `app_core/radio/demod/` package | ✅ landed (shim now 95 lines) |
| `app_utils/image_export.py` | 3391 | `app_utils/image_export/` package | Planned |
| `app_utils/gpio.py` | 3149 | `app_utils/gpio/` package | Planned |
| `app_core/gps/gps_manager.py` | 2893 | split manager / NMEA parsing / survey | Planned |
| `app_core/radio/drivers.py` | 2187 | one module per driver family | Planned |

### 2a. `app_core/radio/demodulation.py` → `app_core/radio/demod/` ✅

The single largest module in the tree, and six unrelated concerns in one file:
Numba JIT kernels, generic DSP helpers, configuration dataclasses, the RBDS
(Radio Broadcast Data System) decoder, the FM demodulator and the AM
demodulator. The RBDS decoder alone is ~2,300 lines and has its own test file
(`tests/test_rbds_demodulation.py`), yet could not be imported without pulling
in the whole FM chain.

| New module | Lines | Contents |
| --- | ---: | --- |
| `demod/kernels.py` | 426 | Numba `@jit` kernels — FM discriminator, de-click, Costas loop, Mueller–Müller timing, syndrome calc, presync scan — plus the Numba availability probe and log-level pinning |
| `demod/rbds_constants.py` | 144 | RT+ AID and content types, RBDS language codes, NRSC-4-B call-sign table, `pi_to_call_sign` |
| `demod/types.py` | 279 | `DemodulatorConfig`, `RBDSData`, `RBDSDecoderStats`, `DemodulatorStatus` |
| `demod/dsp.py` | 332 | `fm_discriminator*`, `fast_decimate`, FIR design, `resample_to`, `StreamingResampler` |
| `demod/rbds_decoder.py` | 1238 | `RBDSDecoder` |
| `demod/rbds_worker.py` | 2293 | `RBDSWorker` |
| `demod/fm.py` | 795 | `FMDemodulator` |
| `demod/am.py` | 96 | `AMDemodulator` |
| `demod/factory.py` | 48 | `create_demodulator` |

The dependency graph is strictly one-directional, with no cycles:

```
kernels ─┬─> dsp ─┬──────────────┐
         │        │              ├─> fm ──┐
         └────────┴─> rbds_worker┘        ├─> factory
rbds_constants ─> rbds_decoder ─┘         │
types ─────────────────────────> am ──────┘
```

`app_core/radio/demodulation.py` remains as a re-export shim so every existing
`from app_core.radio.demodulation import …` keeps resolving — including the
private `_NUMBA_AVAILABLE` that `webapp/routes_monitoring.py` reads.

**Verification.** The split was checked to be pure motion by comparing `ast.dump()`
of every top-level definition before and after: 23 definitions, 23 matches, zero
AST differences. `tests/test_rbds_demodulation.py`, `tests/test_fm_stereo_decoder.py`,
`tests/test_early_decimation.py` and `tests/test_eas_resampler.py` pass unchanged
(103 tests).

**Still over the cap — follow-up needed.** `rbds_worker.py` (2293) and
`rbds_decoder.py` (1238) are each a *single class*, so module-level splitting
cannot shrink them further. `RBDSWorker` has 27 methods covering pilot
estimation, interference notching, timing recovery, Costas carrier recovery and
group decoding — those are five collaborators wearing one class. Bringing them
under the cap means extracting mixins or helper objects, which is a
behaviour-adjacent change and belongs in its own commit with its own review.
Tracked as Phase 2a-ii. `fm.py` (795) needs the same treatment, at lower
priority.

### 2b. `app_utils/image_export.py` → `app_utils/image_export/`

The alert share-image renderer. Seams are already visible in the section
comments:

| New module | Contents |
| --- | --- |
| `theme.py` | `_Theme`, `_resolve_theme`, `_resolve_tier`, urgency/softening helpers |
| `fonts.py` | font loading, `_tw`/`_th`/`_truncate`, `_draw_pill`, caps humanisation |
| `weather_fx.py` | lightning/snow/rain/sun/ember/wind/haze overlay painters |
| `maps.py` | slippy-tile math, tile memory+disk cache, `_fetch_tile`, `_render_map`, storm track, county outlines, scale bar |
| `icons.py` | `_icon_wind`, `_icon_hail`, `_icon_tornado` and friends |
| `render.py` | `generate_alert_image`, layout, section headers |

### 2c. `app_utils/gpio.py` → `app_utils/gpio/`

Four distinct subsystems share one file: the GPIO backend abstraction
(lgpio/sysfs/null), the `GPIOController` + behaviour matrix, the NeoPixel
controller, and the tower-light controller. Suggested split: `backends.py`,
`types.py` (enums + dataclasses), `controller.py`, `behavior.py`, `neopixel.py`,
`tower_light.py`, `config_loaders.py` (the `load_*_from_db` functions).

---

## Phase 3 — Web layer

Flask modules where route handlers and their helpers are interleaved. The
`webapp/audio_archive/` package is the template to copy: helpers in topic
modules, `routes.py` holding only handlers.

| File | Lines | Planned split |
| --- | ---: | --- |
| `webapp/admin/audio_ingest.py` | 3180 | `webapp/admin/audio_ingest/` — `controller.py` (singleton + startup), `sources.py` (DB↔runtime serialisation), `streaming.py` (Icecast + auto-stream), `probe.py` (stream URL testing), `metrics.py`, `routes.py` |
| `webapp/routes_public.py` | 2849 | split by surface: dashboard, alert detail, search, exports |
| `webapp/routes_settings_radio.py` | 2781 | receivers / profiles / diagnostics |
| `webapp/admin/api.py` | 2105 | group endpoints by resource |
| `webapp/admin/certbot.py` | 1946 | certificate ops vs. routes |
| `webapp/admin/maintenance.py` | 1802 | task definitions vs. routes |
| `webapp/routes/alert_verification.py` | 1668 | verification engine vs. routes |
| `app.py` | 1869 | move remaining inline routes/factory helpers into `webapp/` |

## Phase 4 — Long-running services

Highest risk: these are the alert path. Each is dominated by one very large
class, so the split is mixins or extracted collaborators rather than free
functions, and each needs its behaviour pinned by tests before it moves.

| File | Lines | Note |
| --- | ---: | --- |
| `poller/cap_poller.py` | 3996 | `CAPPoller` is 3,340 lines by itself — fetch / parse / persist / relevance / cleanup are the seams |
| `app_utils/eas.py` | 3848 | config loading · SAME header build+describe · TTS normalisation · audio generation · `EASBroadcaster` |
| `app_core/eas_storage.py` | 2824 | |
| `sdr_hardware_service.py` | 2275 | |
| `eas_monitoring_service.py` | 2246 | |
| `app_utils/system.py` | 2580 | mostly independent helpers — easier than it looks |

## Phase 5 — Frontend

| File | Lines | Planned split |
| --- | ---: | --- |
| `static/css/styles.css` | 9390 | `static/css/` partials by concern, concatenated or `@import`ed |
| `templates/admin/gps_dashboard.html` | 8493 | extract JS to `static/js/pages/`, panels to `templates/admin/gps/` partials |
| `templates/system_health.html` | 5749 | same treatment |
| `templates/led_control.html` | 4363 | same treatment |
| `templates/admin/radio.html` | 3006 | same treatment |
| `templates/alert_detail.html` | 2826 | same treatment |
| `templates/audio_monitoring.html` | 2711 | JS already partly in `static/js/audio_monitoring.js` (1982) — finish the move and split that too |

The pattern for templates is the one used on the Audio Archives page in 2.133.1:
inline `<script>` moves to `static/js/pages/<page>.js`, repeated markup moves to
`templates/components/`, and the page keeps only its structure.

---

## Progress log

| Date | Version | What landed |
| --- | --- | --- |
| 2026-08-06 | 2.134.0 | Plan written. Phase 1 (`fips_codes.py`, 3887 → 673) and Phase 2a (`demodulation.py`, 5355 → 9 modules + a 95-line shim). ~7,500 lines of oversized module retired. Follow-up Phase 2a-ii opened for `RBDSWorker`/`RBDSDecoder`. |

## Next up

Phase 2b (`app_utils/image_export.py`) is the recommended next step: it is
library code with no Flask or database involvement, its seams are already
marked by section comments in the file, and it has the same "move verbatim
behind a shim" shape as the two splits that just landed.

Phase 3 needs one decision before it starts — whether `webapp/admin/audio_ingest.py`
should follow `webapp/audio_archive/` exactly (helpers in topic modules,
`routes.py` holding only handlers) or keep its `register_*_routes(app, logger)`
entry point. The latter is how the admin package is wired today, so the split
should preserve it and only move helpers out.
