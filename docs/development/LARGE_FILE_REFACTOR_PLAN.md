# Large File Refactor Plan

**Status:** In progress · **Started:** 2026-08-06

`docs/development/AGENTS.md` sets the size guidance for this repository:

> Aim to keep Python modules under ~400 lines and HTML templates under ~300 lines.
> When adding more than one new class or multiple functions to a module already
> above 350 lines, create or use a sibling module/package instead of expanding
> the existing file.

When this plan was written (2026-08-06) the tree violated that guidance in
**131 Python modules**, **75 templates** and **16 JavaScript files**. That
number will not go to zero in one pass, and trying would produce an
unreviewable diff across the whole codebase. This document is the running
plan: it records the inventory, the extraction strategy per file, and which
phases have landed.

**Do not read those figures as current.** Counting every tracked `*.py` over
400 lines outside `__pycache__`/`node_modules`/`venv`/`migrations`:

| | 2026-08-06 | 2026-08-08 |
| --- | ---: | ---: |
| Python modules > 400 lines | 131 | 162 (137 excluding `tests/`) |
| Templates > 300 lines | 75 | 75 |

The Python figure went **up** while eight files were being split, because the
tree is also growing — the phases below retired roughly 20,000 lines of
oversized module, and new work added more oversized modules than that removed.
The template count has not moved at all: Phase 5 has not started. Treat the
per-phase tables as the source of truth for what has actually landed, and
re-run the count rather than trusting any number written here.

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
`app_core/notifications/alert_image.py` and `webapp/admin/api/`.

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

| File | Lines | Planned split | Status |
| --- | ---: | --- | --- |
| `webapp/admin/audio_ingest.py` | 3180 | `webapp/admin/audio_ingest/` package | ✅ landed — see 3a |
| `webapp/routes_public.py` | 2849 | `webapp/public/` package, split by surface | ✅ landed — see 3b; `logs_data.py` follow-up in 3b-ii |
| `webapp/routes_settings_radio.py` | 2781 | `webapp/radio_settings/` package, split by topic | ✅ landed — see 3c |
| `webapp/admin/api.py` | 2105 | `webapp/admin/api/` package, split by resource | ✅ landed — see 3d |
| `webapp/admin/certbot.py` | 1946 | certificate ops vs. routes | ⏳ |
| `app.py` | 1869 | move remaining inline routes/factory helpers into `webapp/` | ⏳ |
| `webapp/admin/maintenance.py` | 1802 | task definitions vs. routes | ⏳ |
| `webapp/routes/alert_verification.py` | 1668 | verification engine vs. routes | ⏳ |

### 3a. `webapp/admin/audio_ingest.py` → `webapp/admin/audio_ingest/` ✅

The largest Flask module in the tree, and the first web-layer split. Helpers
and handlers were interleaved down its whole length — the stream-URL probe
helpers sit at line 1575, *between* two route handlers.

| New module | Lines | Contents |
| --- | ---: | --- |
| `blueprint.py` | 36 | `audio_ingest_bp` |
| `controller.py` | 231 | Controller singleton, background startup, `_try_acquire_lock`, the Redis metrics bridge |
| `streaming.py` | 262 | Auto-streaming (Icecast) service lifecycle, `_get_icecast_stream_url` |
| `sanitize.py` | 173 | `_sanitize_float`/`_bool`/`_metadata_value`, `_merge_metadata`, `_redact_device_params`, `_db_to_linear` |
| `probe.py` | 155 | `_describe_stream_status`, `_probe_stream_url` |
| `radio_sources.py` | 385 | `ensure_sdr_audio_monitor_source` and the SDR naming/metadata helpers |
| `serialization.py` | 359 | Adapter/DB row → API payload |
| `routes_sources.py` | 88 | The two read endpoints (3a-ii) |
| `routes_sources_write.py` | 389 | create / update / delete (3a-ii) |
| `listing.py` | 226 | Reconciling DB, controller and Redis for the source list (3a-ii) |
| `source_payload.py` | 268 | One audio source rendered to JSON (3a-ii) |
| `routes_source_control.py` | 160 | start / stop / test-stream |
| `routes_rbds.py` | 151 | RBDS history |
| `routes_metrics.py` | 233 | `/api/audio/metrics*` |
| `routes_health.py` | 255 | `/api/audio/health*` and the dashboard page |
| `routes_alerts.py` | 204 | `/api/audio/alerts*` |
| `routes_devices.py` | 159 | devices, waveform, spectrogram, live stream |
| `routes_icecast.py` | 205 | `/api/audio/icecast/*` |

```
blueprint, sanitize, probe        leaves
controller   -> (nothing in-package)
streaming    -> controller
serialization-> controller, sanitize, streaming
radio_sources-> controller, streaming
routes_*     -> blueprint + the helpers each one needs
```

The entry point is unchanged: `register_audio_ingest_routes(app, logger)` stays
the package's only `__all__` entry, so `webapp/admin/__init__.py` did not move.

**Verification.** 69 of the 73 top-level definitions are `ast.dump()`-identical
before and after, every non-blank line of the original lands in exactly one
module, and the full suite is green (1,997 passed). The four deliberate
differences are each pinned by a test in
`tests/test_audio_ingest_package.py`.

**Three things this phase adds to the checklist, all of them consequences of
one file becoming many namespaces.**

1. **A Blueprint's `import_name` changes when it moves.**
   `Blueprint('audio_ingest', __name__)` in a `blueprint.py` resolves to
   `webapp.admin.audio_ingest.blueprint`, one level deeper than before — the
   same class of silent drift as the `__file__` bug in 2b, since Flask derives
   the blueprint's root path (and any template/static folder it later gains)
   from it. `__package__` is the pre-split value, so that is what the new
   module passes. Pinned by a test.
2. **Never import a mutable module global across modules.**
   `remove_radio_managed_audio_source` reads `_audio_controller` directly. A
   generated `from .controller import _audio_controller` binds `None` at import
   time and never sees the singleton `_get_audio_controller` later installs, so
   the local-controller fallback would have silently stopped removing sources —
   no exception, since `if controller and …` simply skips. It goes through a
   new `_peek_audio_controller()` accessor instead, mirroring the
   `_get_auto_streaming_service()` that the sibling global already had. A test
   AST-scans the package for by-value imports of any of the six mutable globals.
3. **A `logger` global that a registration hook rebinds has to be fanned out.**
   `register_audio_ingest_routes` did `global logger; logger = logger_instance`.
   With one module that was the whole story; with fifteen, rebinding the
   package's `logger` leaves every line that actually logs on its own. The hook
   now walks a `_LOGGING_MODULES` tuple, and a test asserts that tuple covers
   every module in the package that defines a `logger`.

**The monkeypatch retarget was load-bearing, and loudly so.** Four fixtures
across three test files reset `_audio_controller`, `_auto_streaming_service`,
`_initialization_started`, `_streaming_lock_file`,
`_audio_initialization_lock_file`, `_start_audio_sources_background`,
`_reload_auto_streaming_from_env`, `_read_audio_metrics_from_redis` and
`_restore_audio_source_from_db_config` on the module. Deliberately *not*
re-exporting the mutable globals from the package `__init__` is what made this
safe: `monkeypatch.setattr` raises `AttributeError` on a missing attribute, so
all 9 patch sites failed immediately instead of turning into silent no-ops. Had
the shim re-exported them for completeness, the resets would have kept
"passing" while resetting nothing.

### 3a-ii. `api_get_audio_sources` → `listing.py` + `source_payload.py` ✅

The one module 3a left over the cap. `routes_sources.py` was 749 lines because
`api_get_audio_sources` alone was 327: a single handler that decoded the audio
service's Redis snapshot in four possible shapes, queried three tables,
reconciled the database against the local controller, and built two different
JSON bodies depending on which won.

Module-level splitting cannot shrink one function, so this is a **collaborator
extraction** — the 2e technique, not the 2a–2d one — and it was verified the
same way.

| Piece | Role |
| --- | --- |
| `RedisControllerState` | What the audio service is publishing: the source map, whether it is usable, whether the service is dead at all, and the streaming block. |
| `_read_redis_controller_state` | Decodes it. The `audio_controller` entry and its nested `streaming` entry may each be a dict or a JSON string, present or absent, well-formed or not. |
| `_latest_metrics_by_source` | One query for the newest persisted metric row per source. |
| `_collect_icecast_status` | Per-source stream stats, local service first, Redis only as a fallback. |
| `_serialize_from_redis` / `_serialize_db_only` | The two JSON bodies, in `source_payload.py`. The third — a live local adapter — was already `serialization._serialize_audio_source`. |
| `build_source_listing` | Orchestration and the envelope counters. |

The write endpoints moved to `routes_sources_write.py` in the same pass, split
along the permission boundary: all three carry
`@require_permission('receivers.configure')`, and neither read endpoint does.

**Verification — the harness came first, as in 2e.**

1. `tests/test_audio_source_listing.py` (12 tests) was written and run green
   against the *pre-refactor* handler, covering all three live-state paths, the
   envelope counters, the dead-service escalation rule, malformed Redis
   payloads and a failing streaming service.
2. Confirmed discriminating before trusting it: five deliberate mutations —
   disabling the dead-service escalation, reversing Redis/database metric
   precedence, inverting `db_only_count`, letting Redis override the local
   streaming service, and dropping the reconstructed Icecast URL — each failed
   exactly the test that covers it, and only that test.
3. A separate dump script rendered the **full response body** for 8 scenarios
   (8 distinct bodies — a harness recording constant state proves nothing)
   against a git worktree at the pre-extraction commit and against the working
   tree: **0 differing bytes**, with the script printing which module it
   patched so a silent fallback to the old shape could not masquerade as a
   match.

**A trap worth recording: a mutation that does not apply looks exactly like a
mutation that survived.** The first run of the five reported four caught and
one survived. The surviving one had been written with the wrong indentation in
its search string, so `str.replace` matched nothing and the "mutant" was the
original code. Assert that the mutation target was found before drawing any
conclusion from the result.

**A second one, from tidying up afterwards:** `ruff check --select F401 --fix`
over the package removed 124 genuinely unused imports — and would have removed
the shim's re-exports too, silently breaking every external importer, except
that ruff exempts `__init__.py` from F401 by default. That exemption is the
only thing that made the command safe. Verify the shim still resolves after any
automated import cleanup rather than relying on it.

### 3b. `webapp/routes_public.py` → `webapp/public/` ✅

The second web-layer split, and structurally unlike 3a. `audio_ingest.py` had
73 top-level definitions sharing a file; `routes_public.py` had **one**. Its
entire body was a single 2,779-line `register(app, logger)` with all 21 route
handlers nested inside it, so no top-level definition could be moved at all.

That turned out to make the split *easier*, not harder. Every handler closed
over exactly two names — `app` (for the `@app.route` decorator) and
`route_logger` — which was checked by walking the AST for `Name` nodes
resolving to `register`'s scope rather than assumed:

| Handler group | Closure variables used |
| --- | --- |
| all 21 handlers | `app`, `route_logger` |
| `terms_page`, `privacy_page` | + `_render_policy_page` (same module) |
| `_render_policy_page` | `policy_docs_root`, `route_logger` |

So each surface keeps its own `register(app, route_logger)` and the handler
bodies move **verbatim** — still nested inside a `register`, just a much
smaller one. No reindentation, no rebinding, no signature changes.

| New module | Lines | Contents |
| --- | ---: | --- |
| `pages.py` | 189 | `/`, `/about`, `/help`, `/style-guide`, `/attribution`, `/support`, `/navigation`, `/terms`, `/privacy`, `/sms-compliance`, `/system_health`, `/audio-monitor`, `_render_policy_page` |
| `sitemap.py` | 115 | `/sitemap.xml` |
| `stats.py` | 693 | `/stats` |
| `alerts.py` | 648 | `/alerts` and `/alerts/export.pdf` |
| `logs_data.py` | 1116 | `_load_logs_data`, via a `build_logs_loader(route_logger)` factory |
| `logs.py` | 265 | `/logs`, `/logs/export.csv`, `/logs/export.pdf` |

`_load_logs_data` is a helper, not a route, and it is the only piece the three
`/logs` handlers share. Wrapping it in `build_logs_loader(route_logger)`
rather than re-signaturing it to take `route_logger` as a parameter keeps its
1,057-line body byte-identical — only the enclosing scope changed. `logs.py`
receives it as a parameter *named `_load_logs_data`*, so the three call sites
resolve it unchanged.

`webapp/routes_public.py` remains as a 31-line shim re-exporting `register`,
so the route-module registry in `webapp/__init__.py` is untouched.

**Verification.** Three independent checks, each confirmed discriminating
before its result was trusted:

1. **AST equality** — 21 of 21 handlers `ast.dump()`-identical before and
   after, plus the every-non-blank-line-placed-exactly-once assertion (2,753
   lines, 0 unplaced).
2. **URL map** — every rule, endpoint and method set, sorted and diffed
   against a git worktree at the pre-split commit: **549 rules, 0
   differences**. Mutation-checked by deleting one `register()` call, which
   the diff caught.
3. **Response bodies** — all 28 public surfaces fetched through the test
   client on both sides and hashed with volatile content scrubbed: **28/28
   identical, 28 distinct digests**.

**A trap this phase hit — an "identical length, different hash" diff is a
scrubbing bug, not a regression.** Nine pages first compared as differing with
byte-for-byte identical lengths, which is the signature of an unscrubbed
fixed-width random value rather than a content change. It was the per-session
CSRF token, which `base.html` emits in three shapes; the harness only knew the
`<input value=…>` one and missed `<meta name="csrf-token">` and
`window.CSRF_TOKEN`. Diff the raw bodies before concluding anything from a
digest mismatch — the length equality was the tell.

**Still over the cap — follow-up needed.** `logs_data.py` (1116),
`stats.py` (693) and `alerts.py` (648) are each dominated by one enormous
function: `_load_logs_data` is 1,057 lines, `stats` is 645, `alerts` is 385.
Module-level splitting cannot shrink a single function, so these need
collaborator extraction with a characterization harness built first — the 2e /
3a-ii technique, not this one. Tracked as Phase 3b-ii.

### 3b-ii. `_load_logs_data` → `webapp/public/logs_sources/` ✅

The first of the three modules 3b left over the cap. `_load_logs_data` was
1,057 lines in **one function**: a seventeen-way `if/elif` chain on `log_type`,
where each branch queried its own table (or the systemd journal, or the
compliance ledger, or an FCC report builder) and shaped rows into the generic
log dict the template renders.

The seam was already drawn by the branches, so the interesting design question
was not *where* to cut but *what contract* the pieces share. Every loader now
takes one `LogQuery` and returns one `LogPage`:

| Piece | Role |
| --- | --- |
| `LogQuery` | `log_type`, `limit`, `service_filter`, `action_filter`, `logger`. The last two are read by exactly one loader each, but travel with every query so the dispatch table can stay uniform. |
| `LogPage` | `display_name`, `rows`, `report_meta`. Only the report loader populates the third field — it is what the template keys off to choose the columnar layout. |
| `resolve_loader` | Exact-match lookup, falling back to the `report_` prefix. Returns `None` for an unknown type, which is how the dispatcher reproduces the old chain "reaching the end without matching". |

| New module | Lines | Contents |
| --- | ---: | --- |
| `common.py` | 83 | `LogQuery`, `LogPage`, `MIN_LOGS_PER_CATEGORY`, `timestamp_sort_key` |
| `database.py` | 329 | `system`, `polling`, `polling_debug`, `audio`, `audio_metrics`, `audio_health`, `gpio` |
| `eas.py` | 304 | `eas_messages`, `decoded_audio`, `manual_activations`, `received_alerts` |
| `audit.py` | 130 | `audit` (with the SQL-level action filter), `compliance` |
| `reports.py` | 146 | The six FCC report kinds and the `report_meta` envelope |
| `services.py` | 90 | The systemd journal category |
| `aggregate.py` | 112 | The "All Logs" merge, fault-tolerance and truncation |
| `aggregate_collectors.py` | 346 | The eleven per-category collectors the merge runs |
| `__init__.py` | 81 | `LOADERS`, `resolve_loader` |

`webapp/public/logs_data.py`: 1116 → **80** lines, now only a dispatch, with
`MIN_LOGS_PER_CATEGORY` re-exported so the old import path still resolves.

**`aggregate.py` is deliberately not a loop over the focused loaders**, however
much it looks like one. Three things differ, and each would be a visible
regression if "de-duplicated":

1. **The row shape.** Merged rows carry a `category` label and a trimmed
   `details` payload; the focused views carry the full payload and an
   `alert_identifier`.
2. **Fault tolerance.** Each merged category is wrapped so one broken table
   cannot take the whole page down; in a focused view a failure *should*
   surface.
3. **The cap.** Each category is limited separately before the merge, so a
   chatty table cannot crowd the others out.

The one thing that *was* de-duplicated is `get_sort_key`, which the `all` and
`services` branches each carried a private copy of — verified `ast.dump()`
-identical before collapsing them into `common.timestamp_sort_key`.

**Verification — the harness came first, as in 2e and 3a-ii.** The function had
**no test coverage at all**, which ground rule 5 says to find out before moving
code rather than after.

1. `tests/test_public_logs_data.py` (79 tests) was written and run green
   against the *pre-refactor* function, asserting the full returned triple —
   display name, every key of every row, and the report metadata — for every
   `log_type`, plus the level-derivation rules, the fallback strings, and the
   limit arithmetic.
2. Confirmed discriminating before being trusted: **15 deliberate mutations,
   15 caught, 0 survived, 0 misapplied**, each failing only the tests that
   cover it.
3. A dump script rendered the loader's full output for **115 scenarios**
   (23 log types × 5 parameter combinations) against a git worktree at the
   pre-refactor commit and against the working tree: **0 differing scenarios,
   26 distinct outputs**. The script prints which module it patched, so a
   silent fallback could not masquerade as a match.
4. The mutation run was repeated against the *refactored* structure — 16
   mutations in their new homes, 16 caught — because passing on one shape says
   nothing about the other.

**Three traps this phase hit.**

1. **`cd` persisted between the two dump runs**, so the "after" run executed in
   the pre-refactor worktree and reported a perfect match against itself. The
   `patched:` line is what caught it: it named `webapp.public.logs_data`, a
   module that no longer carries the systemd collaborators after the split.
   This is precisely the failure the 3a-ii note predicted — print what the
   harness bound to, and check it.
2. **A source restore does not invalidate the bytecode cache.** The mutation
   that swapped two branches of the `audio_health` level rule reordered text of
   *identical length*, and `shutil.move` restored the backup's mtime — so
   CPython saw a matching `(mtime, size)` and kept running the **mutated**
   `.pyc` after the file had been restored. The symptom was one test failing
   in every subsequent mutation, which reads exactly like a flaky test. Purge
   `__pycache__` on restore. (Note the family resemblance to the 3b lesson:
   equal length is a tell, not a coincidence.)
3. **Seeding fires audit listeners.** Inserting `EASMessage` /
   `ManualEASActivation` rows writes `eas.broadcast` / `eas.manual_activation`
   audit entries stamped with the real wall clock, which then showed up as four
   "differing" audit scenarios. They were genuinely different between runs and
   had nothing to do with the refactor — the fix is to seed the audit trail
   deterministically *after* everything else, not to scrub the diff.

**All nine modules are under the 400-line guidance.** `aggregate.py` came out
at 418 on the first pass and was split again along the collector boundary
rather than being recorded as a follow-up.

### 3b-ii (cont). `stats()` → `webapp/public/stats_sections/` ✅

The second of the three. Where `_load_logs_data` was a *dispatch* — exactly one
branch runs per request — `stats()` is an *accumulation*: seventeen
`try/except` blocks in a row, each running a few queries, writing into a shared
`stats_data` dict, and declaring its own fallback so one failing query cannot
lose the whole dashboard. The repeated try/rollback/log/fallback shape is the
thing worth extracting, and it becomes the `StatsSection` contract:

| Piece | Role |
| --- | --- |
| `StatsSection` | `collect`, `fallback`, `error_message`. |
| `collect(stats_data) -> fragment` | Reads the dict built so far — three sections divide by `total_alerts` — and returns only its own keys. |
| `run_sections` | Runs each in order; on failure rolls back, logs, and substitutes the fallback. The rollback is not optional: a failed query leaves the session aborted, so without it every *later* section fails too. |

| New module | Lines | Contents |
| --- | ---: | --- |
| `common.py` | 81 | The contract and the runner |
| `alerts_overview.py` | 215 | Headline counts, boundary/status/severity/event breakdowns, urgency, certainty, message types |
| `timeline.py` | 237 | Hour/weekday/month/year buckets, the recent-alert feed |
| `coverage.py` | 143 | Most-affected boundaries, durations, coverage overlap |
| `broadcast.py` | 173 | Forwarding rate, manual activations, received alerts, latency, relays |
| `polling.py` | 183 | Poller success rate, timings, trend |
| `__init__.py` | 100 | The ordered pipeline and `build_stats_data` |

`webapp/public/stats.py`: 693 → **50** lines. Every module is under the
guidance.

**The pipeline order is declared explicitly in `__init__.py`**, not implied by
module grouping. It is load-bearing — `EAS_FORWARDING`, `MESSAGE_TYPES` and
`COVERAGE_OVERLAP` each divide by `total_alerts` — and keeping the original
sequence also keeps the error-log order unchanged on a broken database.

**Verification.** Harness first, as always: 32 characterization tests written
and green against the pre-refactor handler, reaching the payload by replacing
`render_template` with a capture and calling the view directly (the app's
global login redirect otherwise gets in the way). Mutation-checked at 17/17
before the split and 17/17 after. The rendered payload was then compared
key-by-key against a worktree at the pre-refactor commit across an empty and a
populated database: **70 keys, 0 differences**, with the dump printing the line
count of `register` so the two runs could be proven to be different code.

**Two findings worth recording.**

1. **29 of the 31 trailing `setdefault` calls were dead.** Each section already
   set its keys on *both* its success and its failure path, so the defaults
   could never fire. Only `avg_durations` and `lifecycle_timeline` had no
   producer at all. This was established with a static check, not by eye, after
   a mutation deleting one of the redundant defaults survived — the right
   outcome for a semantically null change, and the signal that sent me looking.
   The section contract now guarantees the property structurally, so only the
   two real defaults remain.
2. **Retargeting mutations is part of the job.** Seven of the seventeen stopped
   applying after the split, because the code they matched had legitimately
   been reworded — `- 5` became `- MAX_YEAR_LOOKBACK`, the success test became
   `_is_success`. "Not applied" proves nothing, so each was rewritten against
   its new home before the run counted.

### 3b-ii (cont). `alerts()` → `webapp/public/alerts_page/` ✅

The last of the three, and a third distinct shape. `_load_logs_data` was a
**dispatch** (one branch runs per request); `stats()` was an **accumulation**
(all sections run, contributing to one dict); `alerts()` is a **pipeline** —
each stage consumes what the last produced, so the modules are stages and the
seams are sequential.

    parse_filters        request args → AlertFilters (clamped, allow-listed)
    load_filter_options  dropdown values + headline counts
    build_alert_query    AlertFilters → a filtered, sorted query
    paginate_alerts      one page of rows, with a fallback
    build_audio_map      generated EAS audio for those rows
    load_manual_messages recent operator-originated activations
    backfill_ipaws_audio lazy extraction for pre-extractor alerts

| New module | Lines | Contents |
| --- | ---: | --- |
| `filters.py` | 210 | `AlertFilters`, the sortable-column allow-list, parsing and clamping |
| `query.py` | 133 | Search, exact filters, date range, VTEC, visibility, sorting |
| `pagination.py` | 101 | `MockPagination`, paginate-with-fallback |
| `options.py` | 88 | Filter dropdown values and headline counts |
| `enrichment.py` | 160 | Audio map, manual activations, lazy IPAWS backfill |
| `pdf_export.py` | 150 | The export's query, blocks and filter summary |
| `__init__.py` | 94 | `build_alerts_page` |

`webapp/public/alerts.py`: 648 → **112** lines. **Phase 3b-ii is complete —
every module in `webapp/public/` is now within the guidance.**

**One duplication left in place, deliberately.** The page and the PDF export
have *separate* query builders, and the export's is a strict subset: it has no
date-range, VTEC or superseded handling, so a PDF exported from a filtered page
can contain rows the page was hiding. Unifying them would have been the
obvious tidy-up and would have silently changed what operators get in a
compliance export. It is documented at the top of `pdf_export.py` and pinned by
`test_pdf_export_ignores_filters_the_page_supports` — recorded as current
behaviour, not endorsed.

**Verification.** 73 characterization tests written and green against the
pre-refactor handlers, reaching the boundary by replacing `render_template` and
`generate_pdf_document` with captures. Mutation-checked 26/26 before and 26/26
after — with **all 26 needing retargeting** in between, since almost every
mutated line had moved or been reworded. Template kwargs and PDF arguments were
then compared across 34 query strings on both routes against a worktree at the
pre-refactor commit: **68 scenarios, 37 distinct outputs, 0 differences.**

**A dead variable removed.** The PDF export captured `per_page` and never used
it — a standing `ruff` F841. `ruff check --select F,E9` is now clean across the
whole of `webapp/public/`.

**The operational lesson from this phase is about the harness, not the code.**
The mutation runner rewrites files in place and restores them afterwards. It
was started in the background while new modules were still being written into
the same directory, and it duly picked the half-written files up as mutation
targets — backing up, mutating and "restoring" them, which left one committed
file altered and one new file silently carrying a mutant's arithmetic. Nothing
was lost (git had the committed file; the new one was caught by reading the
diff), but the rule is simple: **never run a file-rewriting harness in the
background against a tree you are still editing.** Run it in the foreground, or
against a worktree copy.

### 3c. `webapp/routes_settings_radio.py` → `webapp/radio_settings/` ✅

The largest remaining Flask module, and a hybrid of the two shapes seen so far:
eight module-level helpers (like 3a) *plus* a 2,114-line `register()` with 26
handlers nested inside it (like 3b). The 3b closure analysis is what made it
tractable — walking the AST for `Name` nodes resolving to `register`'s scope
showed every handler captures only `app` and `route_logger`:

| Handlers | Closure variables captured |
| ---: | --- |
| 22 | `app`, `route_logger` |
| 2 | `app` |
| 1 | *(none)* |
| 1 | `app`, `route_logger`, `_decode_soapysdr_error` (moved alongside it) |

So the bodies move **verbatim** into topic modules that each keep their own
small `register(app, route_logger)` — no reindentation anywhere.

| New module | Lines | Contents |
| --- | ---: | --- |
| `deps.py` | 129 | The injectable seams and the capture constants |
| `sdr_client.py` | 64 | `_send_sdr_command` |
| `serialization.py` | 162 | `_receiver_to_dict`, `_make_offline_status` |
| `payload.py` | 291 | `_parse_receiver_payload` |
| `sync.py` | 174 | `_sync_radio_manager_state`, `_sync_audio_monitors` |
| `routes_pages.py` | 66 | The two rendered pages |
| `routes_receivers.py` | 259 | Receiver CRUD |
| `routes_receiver_control.py` | 241 | Restart, audio-monitor wiring |
| `routes_devices.py` | 265 | Discovery, capabilities, frequency validation |
| `routes_presets.py` | 49 | Built-in tuning presets |
| `routes_signal.py` | 355 | Waveform, spectrum |
| `routes_monitoring.py` | 64 | Dashboard status, diagnostics summary |
| `routes_diagnostics_status.py` | 306 | Status, SoapySDR error decoding |
| `routes_diagnostics_capture.py` | 275 | IQ capture and download |
| `routes_diagnostics_waterfall.py` | 315 | The waterfall view |
| `routes_diagnostics_analyze.py` | 386 | Capture analysis, auto-gain sweep |
| `__init__.py` | 105 | `register`, fanning out in the original order |

`webapp/routes_settings_radio.py` remains as a **52-line shim**. All 17 modules
are within the guidance.

**The one deliberate deviation from verbatim motion is `deps.py`.** The radio
tests inject fakes for `get_redis_client`, `get_radio_manager`,
`_log_radio_event`, `RADIO_CAPTURE_DIR` and the other capture constants — names
used by up to 19 definitions each, which after the split are spread across ten
modules. A `from .deps import get_redis_client` in each would snapshot the real
object at import time, so a stub set in one place would be silently ignored
everywhere else. Route modules therefore go **through** the module
(`deps.get_redis_client()`), giving exactly one patch point, and a module added
later honours the stub automatically. 51 references were routed this way; every
other line is untouched.

**The shim deliberately does not re-export those names**, so a
`monkeypatch.setattr` aimed at the old location raises `AttributeError` instead
of quietly patching something nothing reads. That is what made the retarget
safe: all 11 patch sites failed immediately and pointed at the real seam.

**Verification.**

1. **AST equality** — 34 of 34 moved definitions `ast.dump()`-identical, plus
   the every-non-blank-line-placed-exactly-once assertion (2,394 lines placed;
   the 54 unplaced are the licence header, the import block, the `register`
   signature and `__all__`).
2. **URL map** — every rule, endpoint and method set diffed against a worktree
   at the pre-split commit: **549 rules, 0 differences**. Mutation-checked by
   dropping one module from the registration tuple, which the diff caught (3
   missing rules).
3. **Logger identity** — `_module_logger` was `logging.getLogger(__name__)`,
   which would have silently become `webapp.radio_settings.deps`. It is pinned
   to the pre-split `"webapp.routes_settings_radio"`, and `register()` derives
   the same `getChild("routes_settings_radio")` once and passes it down, so
   every log line keeps its original name.

**Three traps this phase hit, all in the tooling rather than the code.**

1. **`partition(")\n")` found the licence header, not the import block.** The
   copyright line ends `(KR8MER)`, so a naive split to separate imports from
   body landed on line 3 and the "body" rewrite corrupted every module's
   imports. Split on a sentinel you actually control.
2. **A regex cannot rewrite a name safely; it needs scope.** Three functions
   import `get_redis_client` from `app_core.redis_client` *locally*, shadowing
   the module-level import from `app_core.extensions` — a different object.
   A regex rewrote both the import aliases (`from x import deps.get_redis_client`,
   a syntax error ruff caught) and those shadowed call sites, which would have
   been a silent behaviour change. The rewrite became AST-driven, skipping any
   function that rebinds the name.
3. **`ast.walk()` does not respect scope boundaries.** The first scope-aware
   version collected local bindings with `ast.walk(fn)`, which descends into
   nested functions — so `register()` inherited every handler's local import
   and appeared to shadow names it never touches. Since shadowing is inherited
   downward, that silently skipped the rewrite for *every* handler. The symptom
   was a plausible-looking count (46 rewrites instead of 51). Cut nested
   `FunctionDef`/`Lambda`/`ClassDef` off explicitly when computing a scope.

### 3d. `webapp/admin/api.py` → `webapp/admin/api/` ✅

The easiest of the four web-layer splits so far, and worth recording *why*:
3b and 3c were each one enormous `register()` with the handlers nested inside
it, so the unit of motion was a closure. This file was 21 ordinary top-level
definitions decorated with `@api_bp.route`, which is the 2a–2c shape. Every
definition moved verbatim.

| New module | Lines | Contents |
| --- | ---: | --- |
| `blueprint.py` | 45 | The shared `api_bp` |
| `hostinfo.py` | 81 | Host CPU sample cache, primary-IP detection |
| `motion.py` | 98 | The NWS storm-motion parameter parser |
| `county.py` | 164 | The county-wide heuristic and location terms |
| `display_data.py` | 322 | One alert flattened for the detail views |
| `routes_geometry.py` | 176 | `/api/alerts/<id>/geometry` |
| `routes_alert_detail.py` | 337 | `/alerts/<id>` |
| `routes_alert_export.py` | 265 | PDF, social-share image, IPAWS audio |
| `routes_alerts_list.py` | 321 | `/api/alerts`, `/api/alerts/historical` |
| `routes_boundaries.py` | 141 | `/api/boundaries` |
| `routes_system.py` | 281 | `/api/system_status`, `/api/system_health` |
| `routes_system_history.py` | 136 | `/api/system_health/history` |
| `routes_smart.py` | 165 | `/api/smart_diag` |
| `__init__.py` | 95 | `register_api_routes`, side-effect imports |

```
blueprint, county, hostinfo, motion       leaves
display_data           -> motion
routes_geometry        -> blueprint, county
routes_alert_detail    -> blueprint, county, display_data
routes_alert_export    -> blueprint, display_data
routes_alerts_list     -> blueprint, county
routes_boundaries      -> blueprint
routes_system          -> blueprint, hostinfo
routes_system_history  -> blueprint
routes_smart           -> blueprint
```

All 14 modules are within the guidance. `register_api_routes(app, logger)` is
unchanged and is the package's only `__all__` entry.

**Verification.** 21 of 21 top-level definitions are `ast.dump()`-identical,
every non-blank line of the original lands in exactly one module, and the URL
map is unchanged at **549 rules, 0 differences** against a worktree at the
pre-split commit. The 11 original lines that appear nowhere in the package are
the re-rendered import statements, the module docstring and the
`Blueprint(...)` line.

**Derive import blocks; do not write them.** Hand-writing them produced **127
ruff errors** on the first attempt — a mix of F401 (imports the module does not
need) and F821 (names it does need and did not get). The generator now narrows
each of the *original's* import statements to the names a module actually uses,
which keeps the original grouping and gets the answer right.

**Compute free variables with `symtable`, not by counting `ast.Name` nodes.**
The first derived version still emitted two errors, because
`_extract_alert_display_data` has a local variable named `desc` and name
counting read that as a use of `from sqlalchemy import desc` (F401 + F811).
This is the third appearance of the same bug — Phase 4a hit it with a parameter
named `text`, and 3c with `ast.walk()` ignoring scope boundaries. `symtable`
answers the question directly: at module scope keep names that are referenced
and never bound, and inside a function keep the symbols `is_global()` reports.

**Three dead imports fell out** — `flask.current_app`,
`app_utils.vtec.extract_vtec_identity` and `optimized_parsing.json_dumps` were
imported by the single-file module and used by none of it. Deriving the import
blocks removes this class of cruft for free.

**A blueprint's `root_path` changes even when `import_name` does not.** The
checklist already says to pass the package name rather than the module's
`__name__` (Phase 3a), and `blueprint.py` does — `__package__` is exactly
`webapp.admin.api`. But `import_name` now names a *package* rather than a
module, so Flask derives `root_path` as `webapp/admin/api` where it used to be
`webapp/admin`. It is inert here (no `template_folder`, no `static_folder`, no
`open_resource`), and a test pins that so adding one later is deliberate. Any
split that converts a module into a package of the same name inherits this.

**Tests that read the source as text break on the move, and the failure mode
is asymmetric.** `tests/test_api_field_fixes.py` and
`tests/test_detect_county_wide_false_positive.py` both `open()` the API source
and assert against the text. Pointed at a deleted file they fail loudly, which
is fine — but pointed at a *shim* that no longer holds the code they would pass
vacuously, which is worse than deleting them. Both now scan the package
directory. Add this to the pre-split checklist alongside the
`spec_from_file_location` item: grep the tests for the module's *path*, not
just its import name.

**A new test that passes alone can still fail in the suite — pytest imports
every test module during collection.** The new `putnam_ohio` fixture did
`import app_core.location` and then reached through `app_core.location`. That
works in isolation but raises `AttributeError: module 'app_core' has no
attribute 'location'` under a full run: the submodule attribute is only set on
the parent package by the import that first *executes* the submodule, and by
collection time something else has already put it in `sys.modules`. Use
`importlib.import_module('app_core.location')`, which returns
`sys.modules[name]` and never touches the parent. `tests/conftest.py` documents
the identical trap for `app_core.auth`. **Run a new test file inside the whole
suite, not just on its own** — the failure only appears there, and the first
full run of this phase reported 11 errors that a targeted run could not
reproduce.

**A test that mirrors the logic cannot catch a change to the original.**
`test_detect_county_wide_false_positive.py` reimplemented both heuristics
locally and then grepped the source to confirm the original still matched —
which is what the two brittle source checks were doing there. `_detect_county_wide`
only reads `alert.area_desc` and `alert.raw_json`, so
`tests/test_api_package.py` now exercises the real function against a stub
alert and a monkeypatched `get_location_settings`. Both heuristics are
mutation-checked (2 failures each). Writing those cases also surfaced that
`state_code` holds the two-letter postal code (`OH`), not the spelled-out
state — the `_multi_county_list` guard counts `", <state_code>"` occurrences,
so a fixture using `"ohio"` reinstates the false positive it was written to
prevent.

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
| `app_utils/system.py` | 2580 | ✅ landed — see 4a |

### 4a. `app_utils/system.py` → `app_utils/system/` ✅

The one Phase 4 file that is not a god-class, and the plan's own note —
"mostly independent helpers — easier than it looks" — held up. 47 top-level
definitions shared the file, the internal call graph is strictly acyclic, and
`grep -n "__file__"` came back empty, so this is the 2a–2c technique with no
new hazards.

| New module | Lines | Contents |
| --- | ---: | --- |
| `common.py` | 102 | `SystemHealth`, `_safe_read_text`, `_safe_int`, `_coerce_int`, `_to_bool`, `_is_valid_temperature` |
| `dependencies.py` | 96 | `_collect_dependency_versions` |
| `services.py` | 146 | `_collect_systemd_services` |
| `badges.py` | 189 | `get_distro_logo_url`, `_escape_shields_io_text`, `get_shields_io_badges` |
| `osinfo.py` | 131 | `_collect_operating_system_details`, `_detect_virtualization_environment` |
| `network.py` | 111 | `_collect_network_traffic`, `_select_primary_interface` |
| `device_tree.py` | 110 | `DEVICE_TREE_CANDIDATES`, `_collect_device_tree_details` and the three device-tree readers |
| `block_devices.py` | 163 | `_collect_block_devices`, `_simplify_block_devices` |
| `hardware.py` | 276 | `_collect_hardware_inventory`, `_collect_usb_devices`, `_collect_cpu_details`, `_collect_platform_details` |
| `disks.py` | 99 | `_iter_disk_devices`, `_detect_device_type`, `_nvme_controller_path` |
| `smart.py` | 429 | `_collect_smart_health` |
| `smart_fields.py` | 202 | `NVME_DATA_UNIT_BYTES` and the smartctl/NVMe field extractors |
| `temperature.py` | 177 | `_collect_temperature_readings`, `_add_temperature_entry`, `_parse_temperature_value` |
| `rtc.py` | 127 | `_collect_rtc_status` |
| `subsystems.py` | 147 | `_HARDWARE_SUBSYSTEMS`, `_collect_hardware_subsystems`, `_collect_gps_status` |
| `snapshot.py` | 478 | `_AUDIO_PROCESS_KEYWORDS`, `_is_audio_processing_process`, `build_system_health_snapshot` |

```
common, dependencies, services, badges, network, device_tree,
disks, smart_fields, subsystems                              leaves
block_devices -> common
osinfo        -> common
temperature   -> common
rtc           -> common
hardware      -> common, block_devices, device_tree
smart         -> common, disks, smart_fields
snapshot      -> badges, dependencies, hardware, network, rtc,
                 services, smart, subsystems, temperature, osinfo
```

**Verification.** 48 top-level definitions, 48 `ast.dump()` matches, zero
differences, plus the every-non-blank-line-placed-exactly-once assertion.
`ruff check --select F,E9` is clean on the package apart from one pre-existing
F841. All four production consumers were imported to confirm the shim resolves
(`app_utils/__init__.py`, `app_core/system_health.py`, `webapp/admin/api/`,
`scripts/diagnose_smart.sh`). 43 system-health tests pass.

**The mutable-global rule paid for itself again.** `DEVICE_TREE_CANDIDATES` is
a list that two tests replace wholesale. It is deliberately absent from the
package `__init__`, so both patches raised `AttributeError` instead of silently
patching a name nothing reads — the same loud-failure property that made the
3a retarget safe. They now patch `app_utils.system.device_tree`. The CPU test's
`Path` and `psutil` patches moved to `app_utils.system.hardware` for the same
reason.

**One generator bug worth recording: a parameter name is not a use of an
import.** The script that derived each module's import block from the names its
definitions reference treated the parameter of
`_escape_shields_io_text(text: str)` as a use of `from sqlalchemy import text`,
and gave `badges.py` (and `device_tree.py`, via a local) an import they do not
need. `ruff --select F` caught both as F811/F401. Only `snapshot.py` actually
issues SQL. Lint the generated package before trusting an inferred import
block — name-level inference cannot see scope.

**Still over the cap — follow-up needed.** `snapshot.py` (478) and `smart.py`
(429) are each *one function*: `build_system_health_snapshot` is 406 lines and
`_collect_smart_health` is 396. Module-level splitting cannot shrink them, so
they need collaborator extraction with a characterization harness built first
— the 2e / 3a-ii technique. Tracked as Phase 4a-ii. `build_system_health_snapshot`
is the more tractable of the two: it is a sequence of independent `_collect_*`
calls assembled into one dict, so the seam is already drawn.

---

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
| 2026-08-06 | 2.138.0 | Phase 2d/2e (`gps_manager.py`, 2893 → 2313). The stateless timing math moved as motion; `_handle_sentence` was restructured into `app_core/gps/nmea.py` and verified by characterization rather than AST comparison. |
| 2026-08-06 | 2.140.0 | Phase 3a-ii (`api_get_audio_sources`, 327 → 15 lines + `listing.py`/`source_payload.py`; write endpoints to `routes_sources_write.py`). Every module in `webapp/admin/audio_ingest/` is now under the 400-line guidance. |
| 2026-08-06 | 2.139.0 | Phase 3a (`webapp/admin/audio_ingest.py`, 3180 → 15 modules + a re-exporting `__init__`). First web-layer split; `register_audio_ingest_routes(app, logger)` preserved as the entry point. Three new checklist items: Blueprint `import_name`, mutable-global imports, logger fan-out. |
| 2026-08-07 | 2.141.0 | Phase 3b (`webapp/routes_public.py`, 2849 → 6 surface modules + a package `__init__` + a 31-line shim). First split of a module that was a *single* function — all 21 handlers were nested inside one 2,779-line `register()`. Verified by AST equality, a 549-rule URL-map diff, and 28 response-body digests. |
| 2026-08-07 | 2.142.0 | Phase 4a (`app_utils/system.py`, 2580 → 16 modules + a re-exporting `__init__`). The one Phase 4 file that is not a god-class; pure motion, 48/48 AST matches. 14 of the 16 modules are under the guidance. |
| 2026-08-08 | 2.143.0 | Phase 3b-ii (`_load_logs_data`, 1,057 lines in one function → the `webapp/public/logs_sources/` package; `logs_data.py` 1116 → 80). A `LogQuery`/`LogPage` contract replaced the seventeen-way `if/elif`. The function had no test coverage, so 79 characterization tests were written against the pre-refactor code first; verified by a 115-scenario output diff (0 differences) and two mutation runs (15/15 before, 16/16 after). All nine modules under the guidance. |
| 2026-08-08 | 2.144.0 | Phase 3b-ii cont. (`stats()`, 645 lines in one handler → the `webapp/public/stats_sections/` package; `stats.py` 693 → 50). Seventeen inline try/except blocks became a `StatsSection` contract. 32 characterization tests, mutation-checked 17/17 before and after; payload compared key-by-key against the pre-refactor handler (70 keys, 0 differences). Found 29 of 31 trailing `setdefault` calls to be dead. |
| 2026-08-08 | 2.145.0 | Phase 3b-ii cont. (`alerts()` + its PDF export → the `webapp/public/alerts_page/` package; `alerts.py` 648 → 112). A pipeline rather than a dispatch or an accumulation, so the modules are stages. 73 characterization tests, mutation-checked 26/26 before and after (all 26 needed retargeting); 68-scenario output diff, 0 differences. **Phase 3b-ii complete** — every `webapp/public/` module is within the guidance. |
| 2026-08-08 | 2.146.0 | Phase 3c (`webapp/routes_settings_radio.py`, 2781 → 17 modules + a 52-line shim). All 26 handlers captured only `app` and `route_logger`, so they moved verbatim. 34/34 AST matches; URL map diffed at 549 rules, 0 differences. The one deliberate change is a `deps.py` of injectable seams, reached through the module so a test has a single patch point. |
| 2026-08-08 | 2.146.1 | Not a split — a **regression the Phase 3a split caused**, found while baselining the next one. `webapp/admin/audio_ingest.py` had imported `AudioSourceConfigDB` at its top, so the model was incidentally importable from it; the package `__init__` re-exports only what it means to. `app_core/websocket_push.py` imported it from there twice and both broke silently, taking the audio-source WebSocket push with them. The package's guard test listed its exports by hand and nobody had added this one — it now AST-walks the tree for every `from webapp.admin.audio_ingest import …` and asserts each name resolves. |
| 2026-08-08 | 2.147.0 | Phase 3d (`webapp/admin/api.py`, 2105 → 13 modules + a 95-line `__init__`). 21 ordinary top-level definitions rather than one giant `register()`, so pure motion: 21/21 AST matches, URL map 549 rules / 0 differences. Import blocks are derived with `symtable` after hand-writing them produced 127 ruff errors. Two source-text test files were retargeted, and `_detect_county_wide` is now tested through the real function instead of a local mirror. |

## Next up

**Phase 3b-ii is complete.** All three `webapp/public/` modules that Phase 3b
left over the cap — `logs_data.py`, `stats.py` and `alerts.py` — have landed,
and every module in the package is now within the guidance.

**Phase 3 continued — the remaining web-layer files.** `webapp/admin/api.py`
landed as 3d. `webapp/admin/certbot.py` (1946), `app.py` (1869),
`webapp/admin/maintenance.py` (1802) and
`webapp/routes/alert_verification.py` (1668) are what is left in Phase 3.
Check which shape each one is before planning it: 3d was 21 top-level
definitions and took an afternoon, while 3b and 3c were single enormous
`register()` functions and needed characterization work first.

**Phase 4a-ii — `snapshot.py` (478) and `smart.py` (429)**, the two modules
4a left over the cap. Each is one function; `build_system_health_snapshot` is
the easier one because its body is already a sequence of independent
`_collect_*` calls.

**Phase 4 (`poller/cap_poller.py`, 3996 — the largest Python module in the
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
- [ ] **Grep the tests for the module's *path*, not just its import name** —
      `open('webapp/admin/api.py')`, `py_compile.compile(...)`, `Path(...)`.
      Tests that assert against source *text* break on the move, and the
      failure mode is asymmetric: pointed at a deleted file they fail loudly,
      but pointed at a shim that no longer holds the code they pass vacuously.
      Retarget them at the package directory. (Phase 3d: five such tests.)
- [ ] **Run any new test file inside the full suite, not just on its own.**
      pytest imports *every* test module during collection, so a module you
      never look at can change what yours sees. Reaching a submodule as
      `parent.child` after `import parent.child` is the usual casualty — use
      `importlib.import_module('parent.child')`. (Phase 3d: 11 errors that no
      targeted run reproduced.)
- [ ] **Prefer replacing a source-text assertion with a call to the real
      function.** A test that mirrors the logic locally and then greps the
      original to confirm they still match cannot catch a change to the
      original — that is what the grep was standing in for. If the function
      only needs a stub object and one monkeypatched lookup, test it directly
      and mutation-check it. (Phase 3d.)
- [ ] **Do not name a module `types.py`** — it shadows the stdlib. (Phase 2c.)
- [ ] **Assert every non-blank line of the original lands in exactly one
      module**, so nothing is silently dropped by an off-by-one slice.
- [ ] **Compare `ast.dump()` of every top-level definition** old vs new.
- [ ] **Verify any test retarget is load-bearing** by confirming the tests fail
      without it. A retarget that changes nothing means the test was passing
      vacuously and you have learned something either way.
- [ ] **Import every production consumer** to confirm the shim resolves.
- [ ] **Check what `__name__` is passed to.** A `Blueprint(name, __name__)` or
      `logging.getLogger(__name__)` means something different one directory
      deeper. Pass `__package__` where the pre-split value is what matters.
      (Phase 3a.)
- [ ] **Never let a module import a mutable global from a sibling.**
      `from .x import _some_global` snapshots the value at import time. Add an
      accessor function instead, and AST-scan the package to prove none crept
      in. (Phase 3a: would have silently disabled a cleanup path.)
- [ ] **Do not re-export mutable globals from the shim.** Tests reset them with
      `monkeypatch.setattr`, which raises on a missing attribute but silently
      no-ops on a re-exported one. The loud failure is what tells you where the
      patch has to point. (Phase 3a.)
- [ ] **Fan out any global a registration hook rebinds** — `logger` is the
      usual one. One module meant one global; a package means one per module.
      (Phase 3a.)
- [ ] **Assert a mutation actually applied** before concluding it survived.
      A search string with the wrong indentation replaces nothing, and the
      "surviving mutant" is the untouched original. (Phase 3a-ii.)
- [ ] **Re-check the shim after any automated import cleanup.** `ruff --fix`
      would strip a re-export shim bare; it only spares `__init__.py` because
      F401 exempts it by default. A shim that is *not* an `__init__.py` — like
      `webapp/routes_public.py` — has no such exemption and survives only
      because its `__all__` marks the re-export as used. Verify, don't assume.
      (Phase 3a-ii, 3b.)
- [ ] **Map the closure before splitting a module that is one big function.**
      Nested handlers can be moved verbatim into per-topic `register()`
      functions *only if* you know exactly which enclosing names each one
      captures. Walk the AST for `Name` nodes resolving to the outer scope
      rather than eyeballing it. (Phase 3b: all 21 handlers captured just
      `app` and `route_logger`, which is what made the split pure motion.)
- [ ] **Derive per-module import blocks from the original's own import
      statements; do not hand-write them.** Narrowing each original statement
      to the names a module uses keeps the grouping and gets the answer right.
      Hand-writing them cost 127 ruff errors in one go. (Phase 3d.)
- [ ] **Compute the free-variable set with `symtable`, not `ast.Name` counting
      — name counting cannot see scope.** A *parameter* called `text` reads as
      a use of `from sqlalchemy import text`, and so does a *local variable*
      called `desc`. `symtable` answers directly: at module scope keep names
      referenced but never bound; inside a function keep the symbols
      `is_global()` reports. This bug has now appeared three times (4a, 3c, 3d)
      in three different disguises — it is the single most repeated mistake in
      this plan.
- [ ] **Lint the generated package anyway.** `ruff check --select F,E9` is the
      gate, whatever produced the imports: F401 catches an import nothing
      needs, F821 an import a module needed and did not get. (Phase 4a.)
- [ ] **Rewrite names with the AST, never a regex — a regex has no scope.**
      It will rewrite the alias inside `from x import name` (a syntax error, if
      you are lucky enough for the linter to catch it) and, worse, call sites
      inside functions that shadow the name with their own local import. Phase
      3c had three functions importing `get_redis_client` from a *different*
      module locally; rewriting those would have been a silent behaviour
      change, not a move.
- [ ] **`ast.walk()` does not stop at scope boundaries.** Computing "names
      bound in this function" with `ast.walk` descends into nested functions,
      so an outer function inherits every inner one's local imports. In Phase
      3c that made `register()` appear to shadow names it never touches, and
      because shadowing inherits downward it silently skipped the rewrite for
      every nested handler — leaving a plausible-looking count rather than an
      error. Cut nested `FunctionDef`/`Lambda`/`ClassDef` off explicitly.
- [ ] **Split generated files on a sentinel you control, not on punctuation.**
      A `partition(")\n")` intended to find the end of an import block matched
      the `(KR8MER)` in the copyright header instead, and the "body" rewrite
      then corrupted every module's imports. (Phase 3c.)
- [ ] **Never run a file-rewriting harness in the background against a tree you
      are still editing.** A mutation runner backs up, rewrites and restores
      files in place; started in the background while new modules were being
      written into the same package, it picked the half-written files up as
      targets, leaving one committed file altered and one new file carrying a
      mutant's arithmetic. Run it in the foreground, or point it at a worktree
      copy. (Phase 3b-ii.)
- [ ] **Retarget every mutation after the split, and count "not applied" as a
      failure.** A refactor moves and rewords the lines the mutations matched —
      after the `alerts()` split, all 26 stopped applying. A mutation that
      matched nothing proves nothing, so the run is only meaningful once every
      one has been pointed at its new home. (Phase 3b-ii, and 4 of 17 in the
      `stats()` split.)
- [ ] **Purge `__pycache__` when a harness restores a mutated source.**
      A mutation that swaps two same-length branches leaves the byte count
      unchanged, and a restore that preserves the backup's mtime lets CPython
      reuse the *mutant's* `.pyc`. The tree then keeps running code you believe
      you reverted, and the symptom looks exactly like one flaky test.
      (Phase 3b-ii.)
- [ ] **Make the harness print what it bound to, and read it.** A comparison
      script that silently falls back to the pre-split shape reports a perfect
      match against itself. Naming the patched module is what catches a `cd`
      that leaked between runs, an import that resolved to the wrong tree, or a
      patch target that no longer exists. (Phase 3a-ii, 3b-ii.)
- [ ] **Seed fixtures deterministically, including what the ORM writes for
      you.** Insert-triggered listeners (audit events, `onupdate` stamps) carry
      real wall-clock values, and they will show up as diffs that have nothing
      to do with the refactor. Re-seed those tables last rather than scrubbing
      the comparison until it goes quiet. (Phase 3b-ii.)
- [ ] **Treat an equal-length, unequal-hash diff as a scrubbing bug first.**
      It is the signature of an unscrubbed fixed-width random value, not a
      content change. Diff the raw bodies before concluding a regression.
      (Phase 3b: the per-session CSRF token, emitted in three shapes by
      `base.html`, of which the harness knew only one.)
