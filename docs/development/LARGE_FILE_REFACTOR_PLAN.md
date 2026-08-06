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
6. **Audit every `__file__`-relative path before moving a module.** This is the
   one way "identical code" can still change behaviour: a module in a new
   package sits one directory deeper, so
   `os.path.dirname(os.path.dirname(__file__))` now points somewhere else.
   AST-equality checking cannot catch it — the code really is identical, it
   just means something different. Grep for `__file__` in the file you are
   about to split, and assert the resolved values against the pre-split module
   afterwards. This bit Phase 2b: the brand logo path and the tile disk-cache
   path both silently resolved one level short of the repository root, and
   neither failure raises — `_load_logo()` swallows the error and renders a
   card with no logo. Both are now pinned by tests.
7. **Follow the existing naming convention.** When a module is superseded, the
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
| `app_utils/image_export.py` | 3391 | `app_utils/image_export/` package | ✅ landed |
| `app_utils/gpio.py` | 3149 | `app_utils/gpio/` package | ✅ landed |
| `app_core/gps/gps_manager.py` | 2893 | timing math (2d) + NMEA parsing (2e) extracted | 🚧 2313 — see 2d, 2e |
| `app_core/radio/drivers.py` | 2187 | one module per driver family | ⏳ not started — one 1822-line class |

> **The last two files are not the same kind of problem as the first three.**
> 2a–2c were each *several independent top-level definitions* sharing one file,
> so splitting them was pure motion verifiable by `ast.dump()` comparison.
> These two are each **one god-class**: `GPSManager` was 2741 of
> `gps_manager.py`'s 2893 lines, and `_SoapySDRReceiver` is 1822 of
> `drivers.py`'s 2187. Module-level splitting cannot shrink a single class, so
> a claim in the 2c pull request that Phase 2 was complete was wrong.
>
> The way through is two different techniques, in order:
>
> 1. **Move the stateless parts as motion** (2d) — verify with `ast.dump()`.
> 2. **Extract collaborators for the stateful parts** (2e) — `ast.dump()` is
>    useless here since the code is deliberately restructured, so verify with a
>    **characterization harness built before the refactor**: snapshot all
>    mutated state across a realistic input stream, confirm the baseline is
>    discriminating, then diff after.
>
> `gps_manager.py` has had both applied (2893 → 2313). `drivers.py` has had
> neither.

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

### 2b. `app_utils/image_export.py` → `app_utils/image_export/` ✅

The alert share-image renderer, whose seams were already marked by section
comments in the file.

| New module | Lines | Contents |
| --- | ---: | --- |
| `logo.py` | 71 | Brand logo raster and its cache |
| `layout.py` | 145 | `_Layout` and the landscape/square/portrait/story presets, plus the backwards-compatible `FB_WIDTH`-style constants |
| `palette.py` | 62 | Colour palette, severity/threat colour maps, `_darken`, `_pct_bar_color` |
| `fonts.py` | 116 | Font loading and caching, `_tw`/`_th`/`_truncate` |
| `text.py` | 252 | Local-time formatting and the ALL-CAPS → sentence-case humanizer |
| `icons.py` | 81 | `_icon_wind`, `_icon_hail`, `_icon_tornado`, `_ICON_FN` |
| `theme.py` | 435 | Hazard-family themes, tier badges, urgency heat |
| `drawing.py` | 143 | `_draw_pill`, `_composite`, `_round_image_corners`, `_section_header`, `_card_row` |
| `weather_fx.py` | 429 | Lightning, snow, rain, sun, embers, wind, haze, `_draw_themed_header` |
| `tiles.py` | 257 | Slippy-tile maths, bbox/centroid/zoom, memory LRU + disk cache, `_fetch_tile` |
| `maps.py` | 731 | `_render_map`, storm track, county outlines, SAME union geometry, scale bar |
| `panels.py` | 577 | The seven info-panel section drawers |
| `render.py` | 492 | `generate_alert_image` |

Dependency graph, generated from the actual imports and verified acyclic:

```
logo, layout, palette, fonts, text, icons   leaves
theme       -> palette
drawing     -> fonts, palette
weather_fx  -> drawing, layout, theme
tiles       -> layout
maps        -> fonts, layout, palette, theme, tiles
panels      -> drawing, fonts, icons, palette, text
render      -> drawing, fonts, layout, logo, maps, palette, panels,
               text, theme, weather_fx
```

Here the package `__init__.py` *is* the compatibility shim — it re-exports all
125 names the single-file module exposed (including `logger`), so
`from app_utils.image_export import …` is unchanged for
`app_core/notifications/alert_image.py` and `webapp/admin/api.py`.

**Verification.** 68 top-level definitions, 68 `ast.dump()` matches, zero
differences. The slicing script also asserted that every non-blank line of the
original landed in exactly one module — nothing silently dropped.
`tests/test_image_export_themes.py` passes (123 tests, up from 120).

**One real bug was introduced and caught.** `_LOGO_PATH` and
`_TILE_DISK_CACHE_DIR_DEFAULT` are built by walking up two directories from
`__file__`. That was the repository root when the renderer was a single
`app_utils/image_export.py`; inside the package every module is one level
deeper, so both resolved one short — the share card rendered with **no brand
logo**, and OSM tiles cached into `app_utils/data/tile-cache` (colliding with
the directory Phase 1 had just created for the FIPS table). Neither failure
raises, and the 120 existing tests all still passed. It surfaced only because
a stray `app_utils/data/tile-cache/` appeared in `git status`. Both constants
now derive from a named `_REPO_ROOT` with a comment explaining the depth, and
three tests pin the resolved paths — verified to fail without the fix.

**The test needed two changes, and they are worth understanding before the next
split.** Both come from the same fact: a package has more than one namespace
where the module had one.

1. The test deliberately loads the renderer by file path rather than importing
   it, to avoid pulling in the whole `app_utils` package. Loading a *package*
   that way needs `submodule_search_locations` on the spec, otherwise its
   `from .theme import …` internal imports resolve back through `app_utils` and
   undo the isolation.
2. Nine `monkeypatch.setattr(image_export, …)` calls had to move to the module
   that *calls* the patched name (`tiles` for `_http`, `maps` for `_fetch_tile`
   and `_fetch_county_outlines`, `render` for `_render_map`). Rebinding a name
   on the re-exporting package does not change what `maps._render_map` sees in
   its own globals. This was verified to be load-bearing rather than assumed:
   pointing the patches back at the package makes 5 tests fail.

**Pre-existing issues found, deliberately left alone** (fixing them is a
behaviour change and does not belong in a pure-motion commit):
`maps.py` has an unused `shadow` local (F841, present in the monolith), and
`test_render_map_draws_counties_and_scale_bar` asserts only the output image's
size and mode — despite its name and docstring it never checks that county
outlines or the scale bar were drawn, so it passes whether or not its stubs
take effect.

### Import style

Both packages use **relative** intra-package imports (`from .theme import …`),
matching `webapp/audio_archive/`, `app_core/flask/`, `app_core/config/` and
`app_core/database/`. Beyond consistency this is what lets a test load the
package standalone, as `tests/test_image_export_themes.py` does. `demod/` was
converted from absolute to relative in the same release for this reason.

### 2c. `app_utils/gpio.py` → `app_utils/gpio/` ✅

Four distinct subsystems shared one file: the GPIO backend abstraction
(lgpio/sysfs/null), the `GPIOController` + behaviour manager, the NeoPixel
controller, and the tower-light controller.

| New module | Lines | Contents |
| --- | ---: | --- |
| `pin_types.py` | 166 | `GPIOState`, `GPIOActivationType`, `GPIOBehavior`, the behaviour label/pulse tables, `GPIOActivationEvent`, `GPIOPinConfig`, flash-interval bounds |
| `backends.py` | 426 | `GPIOBackend` Protocol, `_LGPIOBackend`, `_SysfsGPIOBackend`, `_NullGPIOBackend`, gpiozero pin-factory setup, `_BackendPinDevice` |
| `tower_light.py` | 410 | Adafruit and ANDONT command protocols, `TowerLightConfig`, `TowerLightController` |
| `neopixel.py` | 336 | Strip-type constants, `NeopixelConfig`, `_NullNeopixelStrip`, `_make_neo_color`, `NeopixelController` |
| `controller.py` | 1003 | `GPIOController` |
| `behavior.py` | 546 | `GPIOBehaviorManager` |
| `config_loaders.py` | 440 | The four `load_*_from_db` functions and behaviour-matrix (de)serialisation |

```
pin_types, backends, tower_light   leaves
neopixel        -> pin_types
controller      -> backends, pin_types
behavior        -> controller, pin_types
config_loaders  -> neopixel, pin_types, tower_light
```

Each optional-dependency probe moved to sit with its only consumer:
`get_gpio_settings` / `_GPIO_SETTINGS_AVAILABLE` with the database loaders,
`PixelStrip` / `NeopixelColor` / `_NEOPIXEL_LIB_AVAILABLE` with the NeoPixel
controller, `Device` / `OutputDevice` / `MockFactory` with the backends. The
package `__init__.py` re-exports all 72 names the single-file module exposed.

**Verification.** 28 top-level definitions, 28 `ast.dump()` matches, zero
differences, plus the every-line-placed assertion. All six production importers
were imported to confirm they still resolve.

**Two lessons this phase added.**

1. **Do not name a package module `types.py`.** It shadows the stdlib `types`
   for any process whose working directory is the package directory, and the
   stdlib import chain (`dataclasses` → `re` → `enum` → `types`) then fails
   with a confusing partially-initialised-module error. Renamed to
   `pin_types.py`. `app_core/radio/demod/types.py` has the same footgun — it is
   harmless in normal operation, so it was left alone rather than churning
   merged code, but it is a cleanup candidate.
2. **Find monkeypatch targets with an AST scan, not a grep.** String matching
   found 24 of the 31 patch sites here; it missed multi-line
   `monkeypatch.setattr(\n    gpio,\n    "name",\n    …)` calls and a bare
   `real_sleep = gpio.time.sleep` attribute read. Walking the test files'
   ASTs for `setattr` calls whose first argument resolves to the package
   catches every form. The reusable check:

   ```python
   # For each tests/*.py: find setattr calls targeting the package.
   for n in ast.walk(ast.parse(path.read_text())):
       if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == 'setattr' and n.args):
           ...  # report the target expression and attribute name
   ```

---

### 2d. `app_core/gps/gps_manager.py` — stateless timing math extracted ⚠️ partial

`GPSManager` is 2741 lines in one class, 54 methods. Profiling it by `self`
usage splits the class cleanly in two:

| Group | Methods | Lines | Extractable as motion? |
| --- | ---: | ---: | --- |
| Stateless (zero `self` references) | 8 | 386 | ✅ yes — 6 of 8 moved here |
| Stateful (touch `self`) | 46 | 2235 | ❌ no — needs collaborators |

Six of the eight stateless methods (359 lines) moved out verbatim. Two stayed,
deliberately:

- **`_sat_key`** (2 lines) — used only by `_record_sat_seen` /
  `_record_sat_used`, which remain on the manager. Moving a two-line helper
  would add a cross-module hop for no gain.
- **`_scan_capture`** (25 lines) — UBX frame scanning. Its natural home is the
  existing `app_core/gps/ubx.py`, not a timing-statistics module; folding it in
  here would have mixed two unrelated concerns in one commit.

The six that moved:

| New module | Lines | Contents |
| --- | ---: | --- |
| `timing_stats.py` | 342 | `compute_jitter_summary` (adaptive-bucket PPS jitter histogram), `compute_allan_deviation` (overlapping ADEV/TDEV/MTIE at τ = 1/10/100/1000 s), `holdover_seconds`, `derive_leap_state` |
| `sysprobe.py` | 49 | `read_cpu_temp_c`, `safe_read` — two sysfs reads that swallow failure and return `None` |

These were `@staticmethod` in all but name, so they were pure functions
trapped inside a class. Extracting them makes them directly importable and
testable — `tests/test_gps_stability_metrics.py` was already testing them
through `GPSManager._compute_allan_deviation(...)`, reaching past the class to
get at a pure function.

**Verification.** All 6 moved functions are `ast.dump()`-identical to their
originals once the `@staticmethod` decorator and docstring indentation are
normalised (a module-level function indents its docstring 4, not 8); every
non-blank removed line was asserted present in the new modules; and both
implementations were run side by side over 5 interval datasets (including
empty, single-sample and constant edge cases) with **zero output differences**.
135 GPS tests pass.

**What is left, and why it is not motion.** The other 2235 lines are stateful:
`_handle_sentence` alone is 246 lines with 50 `self` references, accumulating
fix state, satellite tracking and publishing as it parses. The plan's original
"split manager / NMEA parsing / survey" wording assumed these were separable
files; they are not. Doing it properly means giving the NMEA parser explicit
state to return rather than mutating `self`, which changes behaviour-bearing
code on the GPS/timing path and cannot be verified by AST comparison. That
deserves its own design pass and reviewed commit — the same conclusion already
recorded for `controller.py` and `behavior.py` in 2c.

**A lesson this phase added — do not let `head` truncate a reference search.**
Grepping for the six method names before extracting appeared to show no test
references, so the first attempt moved them without retargeting any tests. The
search had been piped through `head -20`, and 20 unrelated `_safe_read_text`
matches in `app_utils/system.py` consumed the entire output budget before a
single real hit was printed. 17 tests then failed. When a search is being used
to prove a *negative*, either drop the limit or filter the known-irrelevant
matches out first — a truncated search cannot establish that something is
absent.

---

### 2e. `GPSManager._handle_sentence` → `app_core/gps/nmea.py` ✅

The first **collaborator extraction** in this effort, as opposed to pure
motion. `_handle_sentence` was 246 lines with 50 `self` references: four
sentence branches (GGA/RMC/GSV/GSA) that interleaved NMEA field-mapping with
manager state — satellite history, the holdover anchor, the system-clock sync
policy and a Redis publish.

The seam is *what the sentence says* vs. *what the manager does about it*.
`app_core/gps/nmea.py` (326 lines) owns the former and returns the latter:

| Piece | Role |
| --- | --- |
| `NMEAParseState` | The cross-sentence accumulators — per-talker GSV buckets, the GSA per-cycle PRN union, the cycle flag. Owned by the manager, passed in. |
| `SentenceEffects` | What a sentence implies beyond the fix dict: `sats_seen`, `sats_used`, `saw_3d_fix`, `utc_datetime`. |
| `apply_gga` / `apply_rmc` / `apply_gsv` / `apply_gsa` | One per sentence type. Each takes `(fix, msg, state)` plus config such as `min_satellites`, mutates the fix dict and parse state in place, and returns a `SentenceEffects`. Free of the manager, but not pure. |
| `apply_sentence` | Bumps the per-type counter and dispatches. |

`_handle_sentence` is now 30 lines: take the lock, call `apply_sentence`, apply
the effects, publish. The clock-sync policy moved to its own
`_queue_time_sync`. `_FIX_QUALITY` and `_safe_int` moved to `nmea.py` too — the
NMEA path was their only consumer — and are re-exported from `gps_manager` so
existing imports still resolve. `gps_manager.py`: 2893 → **2313** lines.

**Deferring the effects is safe** because none of `_record_sat_seen`,
`_record_sat_used` or `_mark_3d_fix` reads `self._fix`; that was checked by AST
before the seam was drawn, not assumed. Had any of them read the fix dict,
applying effects after the parse instead of mid-parse could have changed
behaviour.

**Verification — this is where a characterization harness earns its keep.**
`ast.dump()` comparison is useless here: the code is deliberately restructured.
So the safety net was built *first*, against the pre-refactor code:

1. A 28-sentence multi-GNSS stream — full cycles, multi-constellation GSV
   groups, several GSAs per cycle, no-fix → 2D → 3D transitions, empty GLGSA,
   blank/malformed fields, out-of-order GSV group numbers.
2. Snapshot **all** mutated state after every sentence: the fix dict, the GSV
   buckets, the GSA accumulator and cycle flag, the pending time sync, the
   per-PRN satellite history and the 3D-fix anchor.
3. Confirm the baseline is discriminating — 28 frames, **28 distinct states**.
   A harness that records constant state proves nothing.
4. Refactor, re-run, diff with wall-clock timestamps scrubbed:
   **0 differing frames of 28.**

`tests/test_gps_nmea_sentences.py` (19 tests) makes the harness permanent and
adds direct coverage the old shape could not have: each rule is now assertable
without constructing a `GPSManager`. Two of them were mutation-checked rather
than trusted — reverting the GSV per-talker bucketing and the GSA union each
failed exactly one test, and only that test.

**Two traps this phase hit.**

1. **Re-typing a constant instead of moving it.** `_FIX_QUALITY` and
   `_safe_int` were re-written from memory into the new module. Both were
   wrong: the fix-quality labels came out `"invalid"/"gps"/"dgps"` instead of
   `"no_fix"/"gps_fix"/"dgps_fix"`, and the re-typed `_safe_int` dropped the
   `int(float(s))` conversion so `"12.0"` would raise instead of yielding 12.
   Neither raises at import; both would have silently changed the dashboard.
   Move shared helpers by *reference* — grep for the real definition and cut
   it — and never re-type one from memory.
2. **A truncated grep cannot prove a negative.** See 2d: `| head -20` hid every
   real hit behind unrelated matches, and the conclusion drawn from it ("no
   test references these") was wrong.

### What is left in `gps_manager.py`

2313 lines, still over the guidance. The remaining bulk is the gpsd client
(`_gpsd_reader_loop`, `_gpsd_connect`, `_handle_gpsd_tpv`, `_handle_gpsd_sky`,
the watchdog and daemon restart), the serial reader loop, the PPS/kernel-PPS
handling and `get_status`. Each is a plausible next collaborator and each wants
the same treatment: characterize first, then extract. `app_core/radio/drivers.py`
(one 1822-line `_SoapySDRReceiver`) is untouched and needs the same approach.

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
| 2026-08-06 | 2.135.0 | Phase 2b (`image_export.py`, 3391 → 13 modules + a re-exporting `__init__`). `demod/` converted to relative imports to match the repo convention. Largest remaining Python module is now `poller/cap_poller.py` at 3996. |
| 2026-08-06 | 2.136.0 | Phase 2c (`gpio.py`, 3149 → 7 modules + a re-exporting `__init__`). Phase 2 complete: the four biggest library modules — 15,043 lines between them — are now 42 focused modules. A pre-split checklist was added, distilled from the three bugs the earlier phases hit. |

## Next up

Phase 2 is complete. Every remaining oversized module is either Flask-coupled
(Phase 3), on the alert path (Phase 4), or frontend (Phase 5) — all three are
meaningfully riskier than the library splits that have landed so far, and none
should be attempted without first running the pre-split checklist below.

**Phase 3 — `webapp/admin/audio_ingest.py` (3180)** is the recommended next
step, being the largest of the web-layer modules and the one with the clearest
helper/handler seam. One decision to make before starting: whether it should
follow `webapp/audio_archive/` exactly (helpers in topic modules, `routes.py`
holding only handlers) or keep its `register_*_routes(app, logger)` entry
point. The latter is how the admin package is wired today, so the split should
preserve it and only move helpers out.

**Phase 4 (`poller/cap_poller.py`, 3996 — now the largest Python module in the
tree, and `app_utils/eas.py`, 3848)** is the highest-risk work in this plan:
both sit directly on the alert path, and each is dominated by one very large
class, so the split means extracted collaborators rather than free functions.
Pin the behaviour with tests *before* moving anything.

## Pre-split checklist

Run all of this before touching a file. Each item exists because skipping it
cost a debugging cycle in an earlier phase.

- [ ] **`grep -n "__file__"`.** Every `__file__`-relative path shifts meaning
      when a module moves one directory deeper. AST-equality cannot catch it.
      Assert the resolved values against the pre-split module afterwards.
      (Phase 2b: silently dropped the brand logo from every share image.)
- [ ] **AST-scan the tests for `monkeypatch.setattr` targets**, not grep — grep
      misses multi-line calls and bare attribute reads. Retarget each to the
      module that *calls* the name. (Phase 2c: grep found 24 of 31 sites.)
- [ ] **Check for tests loading the module by file path**
      (`spec_from_file_location`). A package needs `submodule_search_locations`
      on the spec. (Phase 2b.)
- [ ] **Do not name a module `types.py`** — it shadows the stdlib. (Phase 2c.)
- [ ] **Assert every non-blank line of the original lands in exactly one
      module**, so nothing is silently dropped by an off-by-one slice.
- [ ] **Compare `ast.dump()` of every top-level definition** old vs new.
- [ ] **Verify any test retarget is load-bearing** by confirming the tests fail
      without it. A retarget that changes nothing means the test was passing
      vacuously and you have learned something either way.
- [ ] **Import every production consumer** to confirm the shim resolves.
