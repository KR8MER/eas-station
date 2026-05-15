# Logo options — pick one

PR #2119 globalized **one** logo without first showing you the alternatives. This folder restores every logo variant that existed at the parent of that PR so you can pick the one you actually want.

All six candidates below are recovered from git (parent of commit `1feaeb84`). Each shows a `*-preview.png` rendered from the source SVG; the SVG itself is the authoritative artwork.

For comparison, `CURRENT-IN-USE.png` is the rasterized PNG that PR #2119 made global (this is the one that was wrong).

---

## A — `eas-station-logo.svg` *(square icon — 512×512)*

> Modern emergency alert monitoring system with signal waveform visualization.
> This is the one PR #2119 picked (rasterized to `CURRENT-IN-USE.png`).

![A](eas-station-logo-preview.png)

---

## B — `eas-station-logo-v2.svg` *(wordmark — 900×200, theme-aware)*

Uses CSS custom properties (`--primary-color`, `--secondary-color`, …) so it re-tints with the active theme.

![B](eas-station-logo-v2-preview.png)

---

## C — `eas-station-logo-v3.svg` *(wordmark — 850×200, theme-aware)*

![C](eas-station-logo-v3-preview.png)

---

## D — `eas-station-logo-v4.svg` *(wordmark — 800×180, theme-aware)*

![D](eas-station-logo-v4-preview.png)

---

## E — `eas-system-wordmark.svg` *(wordmark — 800×200, hard-coded slate/grey palette)*

The original `templates/partials/logo_wordmark.html` partial pointed at this file before PR #2119 inlined it.

![E](eas-system-wordmark-preview.png)

---

## CURRENT-IN-USE (the one PR #2119 made global — for comparison)

![current](CURRENT-IN-USE.png)

---

## How to choose

Reply with the letter (A / B / C / D / E). I will then:

1. Restore the chosen SVG to `static/img/` under whichever filename the consumers expect.
2. Re-point every consumer (favicons in `templates/base.html` & `templates/partials/common_head.html`, the share-image header in `app_utils/image_export.py`, and `templates/partials/logo_wordmark.html`) at the chosen asset.
3. Drop the wrong `static/img/eas-station-logo.png` (and this `docs/branding/logo-options/` folder, unless you want it kept as a reference archive — let me know).

If you want a **combination** (e.g. icon A for favicons + wordmark C for on-page brand) just say so and I will wire both.
