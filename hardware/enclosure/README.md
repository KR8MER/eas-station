# EAS Station — 3D-printable enclosure

A parametric desktop case for a Raspberry Pi based EAS Station build with a
front-mounted **Noritake GU140x32F-7000B** VFD, a **0.96″ SSD1306** OLED, and a
navigation push-button. The model is a single OpenSCAD source that exports two
printed parts (**base** + **lid**).

> **Status: starting point, not a drop-in.** The Raspberry Pi geometry is from
> the official mechanical spec and is trustworthy. The *display-module*
> dimensions are best-effort defaults — the project documentation specifies the
> electronics (models, voltages, pinouts) but **not** the modules' millimetre
> outlines. Every uncertain value in `eas_station_case.scad` is tagged
> `// VERIFY`. **Measure your actual modules (or pull the datasheets) and update
> those variables before you print.** See the checklist below.

## Files

| File | Purpose |
|---|---|
| `eas_station_case.scad` | Parametric model — all dimensions are named variables at the top. |
| `README.md` | This document. |

## What it provides

- Raspberry Pi 5 standoffs on the official `58 × 49 mm` hole pattern (M2.5).
- Front wall with a **VFD glass window** + 4 mounting holes, an **OLED window**
  + 4 mounting holes, and a **12 mm button** hole.
- Internal **mounting bosses** behind the front wall for the display screws.
- **Service slots** on the left/right walls for the Pi's USB/Ethernet and
  USB-C/HDMI port banks (generous openings rather than per-connector holes —
  see "Refining the I/O" below).
- Rear **GPS antenna (SMA) feedthrough** and an optional **DB9/USB-serial slot**
  for the VFD link.
- Side and lid **ventilation slots** (the system runs ~12 W; passive cooling).
- Corner **screw posts** and a lipped, counter-bored **lid** (M3).

The Pi is oriented with its long (85 mm) edge along the case depth so its port
banks face the side walls, leaving the wide front face free for the 117 mm-wide
VFD module (which is what sets the case width).

## Render the STLs

Install [OpenSCAD](https://openscad.org/) (free), then:

```sh
cd hardware/enclosure
openscad -D 'part="base"' -o eas_station_base.stl eas_station_case.scad
openscad -D 'part="lid"'  -o eas_station_lid.stl  eas_station_case.scad
```

Open the file in the OpenSCAD GUI to preview the assembled view with translucent
"ghost" blocks for the Pi, HAT stack, and displays (`part="all"`), which makes
it easy to spot fit problems before slicing. The computed exterior envelope is
printed to the console via `echo` on every render.

## ⚠️ Verify before printing

Update these in `eas_station_case.scad` from your real parts:

- [ ] **VFD** — `vfd_mod_w/h/d`, `vfd_view_w/h`, `vfd_hole_dx/dy`, `vfd_view_yoff`
      (Noritake GU140x32F-7000B datasheet, your revision).
- [ ] **OLED** — `oled_mod_w/h`, `oled_view_w/h`, `oled_view_yoff`,
      `oled_hole_dx/dy` (measure the Argon Industria SSD1306 module).
- [ ] **HAT stack height** — `hat_stack_h` (GPS HAT + stacked headers/OLED).
- [ ] **Side I/O slots** — `io_slot_left_*`, `io_slot_right_*`, `io_slot_z`;
      confirm against your Pi model's port positions, then dry-fit.
- [ ] **Button** — `btn_d` for your momentary switch.
- [ ] **Wall/fit** — `clearance` to suit your printer (lid lip + slots).

Then print a **front-wall test coupon** first: set the displays close, render
`base`, and slice just the first ~10 mm of the front to confirm the windows,
holes, and button line up — cheaper than a full case reprint.

## Suggested print settings

- Material: **PETG** (heat tolerance near the Pi) or PLA for a cool room.
- Layer height: 0.2 mm; walls: 3 perimeters; infill: 20–25 %.
- Base: print floor-down. Supports only needed for the rear DB9 slot and the
  side service slots (they bridge a short span — "supports on build plate only").
- Lid: print top-down (lip up); no supports.

## Assembly

1. Fasten the **VFD** and **OLED** to the inside of the front wall through their
   windows into the printed bosses (M3 / M2.5, ~6 mm self-tapping).
2. Mount the **Pi** on the four standoffs (M2.5).
3. Stack the **GPS HAT** (low-profile stacking header recommended so the lid
   still closes) and route the OLED I2C + button leads.
4. Feed the **GPS antenna** through the rear SMA hole; bring the **VFD serial**
   (USB-serial or DB9) out the rear slot; route Pi USB-C power through the right
   service slot.
5. Drop the **lid** on and fix the four M3 corner screws.

## Refining the I/O (optional, flush finish)

The side slots intentionally expose the whole Pi port bank because exact Pi 5
port coordinates aren't published in this repo. For a flush, per-connector
finish: import an official Raspberry Pi 5 STEP model, align it to the `pi_x0 /
pi_y0 / pi_z` origin used here, and replace `side_io_slots()` with individual
USB-A / RJ45 / USB-C / micro-HDMI cutouts at the measured positions.

## Bill of materials (case fasteners)

| Qty | Item | Use |
|---|---|---|
| 4 | M2.5 × 6 mm self-tapping | Pi board to standoffs |
| 4 | M3 × 6 mm self-tapping (or per VFD datasheet) | VFD to front bosses |
| 4 | M2.5 × 6 mm self-tapping | OLED to front bosses |
| 4 | M3 × 12 mm | Lid to corner posts |
| 1 | 12 mm momentary push-button | Front navigation button |
| 1 | SMA bulkhead (if external GPS antenna) | Rear feedthrough |

Electronics (Pi, GPS HAT, VFD, OLED, relays, etc.) and their wiring are covered
in the project's `docs/hardware/` guides.
