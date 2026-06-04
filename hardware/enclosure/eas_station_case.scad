// =============================================================================
// EAS Station — parametric desktop enclosure
// =============================================================================
//
// A 3D-printable two-part case (base + lid) for a Raspberry Pi based EAS Station
// build with a front-mounted Noritake GU140x32F-7000B VFD, a 0.96" SSD1306 OLED,
// and a navigation push-button.
//
// EVERYTHING is parametric. The Raspberry Pi mechanical spec is fixed and
// trustworthy; the *display module* outlines below are best-effort defaults
// because the project docs do not publish their millimetre dimensions. Each
// uncertain value is tagged "VERIFY" — measure your actual module (or pull the
// datasheet) and update the variable before printing. Nothing else needs to
// change for the geometry to follow.
//
// Render a single part for slicing with the `part` selector, e.g.:
//   openscad -D 'part="base"' -o base.stl eas_station_case.scad
//   openscad -D 'part="lid"'  -o lid.stl  eas_station_case.scad
//
// Author: EAS Station project. License follows the repository (AGPL-3.0 / commercial).
// =============================================================================

// ---- What to render -------------------------------------------------------
part = "all";          // [all, base, lid]
preview_modules = true; // show translucent display/Pi blocks in the "all" view only

$fn = 56;

// ---- Print fit / shell ----------------------------------------------------
wall        = 2.6;     // outer wall thickness
floor_t     = 2.6;     // base floor thickness
lid_t       = 2.6;     // lid top thickness
clearance   = 0.40;    // generic print-fit clearance (lid lip, slots)
corner_r    = 4;       // exterior corner radius

// ---- Raspberry Pi 5 board (fixed — RPi mechanical spec) --------------------
pi_l        = 85;      // board length (X here)  — Pi long edge
pi_w        = 56;      // board width  (Y here)
pi_hole_dx  = 58;      // mounting-hole spacing along board length
pi_hole_dy  = 49;      // mounting-hole spacing along board width
pi_hole_in  = 3.5;     // hole centre inset from board edge
pi_hole_d   = 2.7;     // M2.5 clearance
standoff_h  = 7;       // lift the board off the floor for cabling
standoff_od = 6;
standoff_id = 2.4;     // self-tapping pilot for M2.5

// The Pi is mounted with its long (85 mm) edge running along case depth (Y),
// so its USB/Ethernet and USB-C/HDMI port banks face the LEFT/RIGHT walls and
// the wide front wall is free for the VFD. Port banks are exposed through
// generous "service slots" rather than per-connector holes, because exact Pi 5
// port coordinates are not published here — refine into individual cutouts if
// you want a flush finish (see README).
pi_clear_below = standoff_h;     // gap under board
hat_stack_h    = 42;             // GPS HAT + stacked OLED/headers   // VERIFY

// ---- VFD: Noritake GU140x32F-7000B (front panel) --------------------------
// VERIFY all five against the Noritake datasheet for your exact revision.
vfd_mod_w   = 117.0;   // module PCB width            // VERIFY
vfd_mod_h   = 38.0;    // module PCB height           // VERIFY
vfd_mod_d   = 16.0;    // module depth behind panel   // VERIFY
vfd_view_w  = 64.5;    // visible glass width         // VERIFY
vfd_view_h  = 16.0;    // visible glass height        // VERIFY
vfd_hole_dx = 110.4;   // mounting-hole X spacing     // VERIFY
vfd_hole_dy = 31.4;    // mounting-hole Y spacing     // VERIFY
vfd_hole_d  = 3.4;     // M3 clearance
vfd_view_yoff = 0;     // glass centre offset vs module centre (Z) // VERIFY

// ---- OLED: 0.96" SSD1306 I2C module ---------------------------------------
// VERIFY against your Argon Industria SSD1306 module.
oled_mod_w  = 27.3;    // VERIFY
oled_mod_h  = 27.8;    // VERIFY
oled_view_w = 21.8;    // active glass width          // VERIFY
oled_view_h = 11.2;    // active glass height         // VERIFY
oled_view_yoff = 4.0;  // glass sits above module centre (Z) // VERIFY
oled_hole_dx = 23.0;   // VERIFY
oled_hole_dy = 23.5;   // VERIFY
oled_hole_d  = 2.6;    // M2.5 clearance

// ---- Front-panel navigation button ----------------------------------------
btn_d       = 12.2;    // panel hole for a 12 mm momentary push button

// ---- Front-panel layout (centres, measured from interior) -----------------
// VFD on top, OLED + button on a lower strip.
panel_pad_top = 9;
gap_vfd_oled  = 12;

// ---- Connector access (service slots + feedthroughs) ----------------------
// Left wall: Pi USB-A x2 stacks + Ethernet bank.  Right wall: USB-C + HDMI.
io_slot_left_w  = 56;  io_slot_left_h  = 18;  // VERIFY position/size
io_slot_right_w = 40;  io_slot_right_h = 14;  // VERIFY
io_slot_z       = 4;   // slot bottom above board top
sma_d           = 6.5; // GPS antenna SMA bulkhead feedthrough (rear)
db9_w           = 31;  db9_h = 13;            // optional DB9 (VFD serial) rear slot
usb_serial_slot = true; // cut the rear DB9/USB-serial slot

// ---- Lid fixing -----------------------------------------------------------
post_d      = 9;       // corner screw posts
post_screw  = 3.2;     // M3 clearance through lid / pilot in post
vent_slot_w = 2.6;
vent_count  = 9;

// ===========================================================================
// Derived dimensions
// ===========================================================================
// Footprint must clear the VFD width and the Pi depth, plus working margins.
inner_w = max(vfd_mod_w + 8, pi_w + 20);          // X (front face width)
inner_d = pi_l + max(vfd_mod_d, 14) + 10;         // Y (depth)
inner_h = max(standoff_h + hat_stack_h + 6,       // electronics stack
              vfd_view_h + gap_vfd_oled + oled_mod_h + panel_pad_top + 10);

ext_w = inner_w + 2*wall;
ext_d = inner_d + 2*wall;
ext_h = inner_h + floor_t;

// Pi placement (board origin), centred in X, pushed toward the rear (+Y)
pi_x0 = wall + (inner_w - pi_w)/2;     // board width pi_w runs along X
pi_y0 = wall + inner_d - pi_l - 6;     // board length pi_l runs along Y
pi_z  = floor_t;

// Front wall display centres (Z from floor)
vfd_cz  = floor_t + inner_h - panel_pad_top - vfd_view_h/2;
oled_cz = vfd_cz - vfd_view_h/2 - gap_vfd_oled - oled_view_h/2;
oled_cx = ext_w/2 - 16;
btn_cx  = ext_w/2 + oled_mod_w/2 + 14;
btn_cz  = oled_cz;

// ===========================================================================
// Helpers
// ===========================================================================
module rrect(w, d, h, r) {
    // rounded-corner box (rounded on the vertical edges only)
    linear_extrude(height = h)
        offset(r = r) offset(r = -r)
            square([w, d], center = false);
}

module tube(h, od, id) {
    difference() {
        cylinder(h = h, d = od);
        translate([0, 0, -0.5]) cylinder(h = h + 1, d = id);
    }
}

// ===========================================================================
// Base
// ===========================================================================
module pi_standoffs() {
    for (sx = [pi_hole_in, pi_w - pi_hole_in])
        for (sy = [pi_hole_in, pi_l - pi_hole_in])
            translate([pi_x0 + sx, pi_y0 + sy, floor_t])
                tube(standoff_h, standoff_od, standoff_id);
}

module corner_posts() {
    inset = corner_r + post_d/2;
    for (px = [inset, ext_w - inset])
        for (py = [inset, ext_d - inset])
            translate([px, py, floor_t])
                tube(inner_h, post_d, post_screw);
}

// Boss behind the front wall to receive a display mounting screw.
module front_boss(cx, cz, depth) {
    translate([cx, wall, cz]) rotate([-90, 0, 0])
        cylinder(h = depth, d = standoff_od);
}

module front_screw_hole(cx, cz, depth) {
    translate([cx, -1, cz]) rotate([-90, 0, 0])
        cylinder(h = depth + wall + 2, d = standoff_id);
}

module shell() {
    difference() {
        rrect(ext_w, ext_d, ext_h, corner_r);
        translate([wall, wall, floor_t])
            rrect(inner_w, inner_d, inner_h + 1, max(0.1, corner_r - wall));
    }
}

module display_cutouts() {
    // VFD glass window (front wall is the -Y face at y≈0)
    translate([ext_w/2 - vfd_view_w/2, -1, vfd_cz - vfd_view_h/2])
        cube([vfd_view_w, wall + 2, vfd_view_h]);
    // VFD mounting holes (4)
    for (hx = [-vfd_hole_dx/2, vfd_hole_dx/2])
        for (hz = [-vfd_hole_dy/2, vfd_hole_dy/2])
            translate([ext_w/2 + hx, -1, vfd_cz + hz])
                rotate([-90, 0, 0]) cylinder(h = wall + 2, d = vfd_hole_d);

    // OLED glass window
    translate([oled_cx - oled_view_w/2, -1, oled_cz - oled_view_h/2])
        cube([oled_view_w, wall + 2, oled_view_h]);
    // OLED mounting holes (4) — referenced to module centre, glass offset applied
    for (hx = [-oled_hole_dx/2, oled_hole_dx/2])
        for (hz = [-oled_hole_dy/2, oled_hole_dy/2])
            translate([oled_cx + hx, -1, oled_cz - oled_view_yoff + hz])
                rotate([-90, 0, 0]) cylinder(h = wall + 2, d = oled_hole_d);

    // Navigation button
    translate([btn_cx, -1, btn_cz]) rotate([-90, 0, 0])
        cylinder(h = wall + 2, d = btn_d);
}

module side_io_slots() {
    z0 = floor_t + pi_clear_below + io_slot_z;
    // Left wall (-X)
    translate([-1, pi_y0 + (pi_l - io_slot_left_w)/2, z0])
        cube([wall + 2, io_slot_left_w, io_slot_left_h]);
    // Right wall (+X)
    translate([ext_w - wall - 1, pi_y0 + (pi_l - io_slot_right_w)/2, z0])
        cube([wall + 2, io_slot_right_w, io_slot_right_h]);
}

module rear_cutouts() {
    // GPS antenna feedthrough
    translate([ext_w/2 + vfd_mod_w/2 - 8, ext_d - wall - 1, floor_t + inner_h - 12])
        rotate([-90, 0, 0]) cylinder(h = wall + 2, d = sma_d);
    // Optional DB9 / USB-serial slot for the VFD link
    if (usb_serial_slot)
        translate([ext_w/2 - db9_w/2, ext_d - wall - 1, floor_t + 6])
            cube([db9_w, wall + 2, db9_h]);
}

module side_vents() {
    // Ventilation slots in both side walls, above the board
    sp = inner_d / (vent_count + 1);
    z0 = floor_t + inner_h*0.30;
    zh = inner_h*0.45;
    for (i = [1 : vent_count])
        for (xw = [-1, ext_w - wall - 1])
            translate([xw, wall + i*sp - vent_slot_w/2, z0])
                cube([wall + 2, vent_slot_w, zh]);
}

module base() {
    difference() {
        union() {
            shell();
            pi_standoffs();
            corner_posts();
            // Display mounting bosses behind the front wall
            for (hx = [-vfd_hole_dx/2, vfd_hole_dx/2])
                for (hz = [-vfd_hole_dy/2, vfd_hole_dy/2])
                    front_boss(ext_w/2 + hx, vfd_cz + hz, 6);
            for (hx = [-oled_hole_dx/2, oled_hole_dx/2])
                for (hz = [-oled_hole_dy/2, oled_hole_dy/2])
                    front_boss(oled_cx + hx, oled_cz - oled_view_yoff + hz, 6);
        }
        display_cutouts();
        side_io_slots();
        rear_cutouts();
        side_vents();
        // pilots into the front bosses
        for (hx = [-vfd_hole_dx/2, vfd_hole_dx/2])
            for (hz = [-vfd_hole_dy/2, vfd_hole_dy/2])
                front_screw_hole(ext_w/2 + hx, vfd_cz + hz, 6);
        for (hx = [-oled_hole_dx/2, oled_hole_dx/2])
            for (hz = [-oled_hole_dy/2, oled_hole_dy/2])
                front_screw_hole(oled_cx + hx, oled_cz - oled_view_yoff + hz, 6);
    }
}

// ===========================================================================
// Lid
// ===========================================================================
module lid() {
    inset = corner_r + post_d/2;
    difference() {
        union() {
            // top plate
            rrect(ext_w, ext_d, lid_t, corner_r);
            // inner lip that drops into the shell
            translate([wall + clearance, wall + clearance, -3])
                rrect(inner_w - 2*clearance, inner_d - 2*clearance, 3,
                      max(0.1, corner_r - wall));
        }
        // screw holes over the corner posts
        for (px = [inset, ext_w - inset])
            for (py = [inset, ext_d - inset])
                translate([px, py, -4]) cylinder(h = lid_t + 6, d = post_screw + 0.3);
        // counterbores
        for (px = [inset, ext_w - inset])
            for (py = [inset, ext_d - inset])
                translate([px, py, lid_t - 1.6]) cylinder(h = 3, d = post_screw + 3.2);
        // top vent slots
        sp = ext_w / (vent_count + 1);
        for (i = [1 : vent_count])
            translate([i*sp - vent_slot_w/2, ext_d*0.30, -1])
                cube([vent_slot_w, ext_d*0.40, lid_t + 2]);
    }
}

// ===========================================================================
// Visual-only preview blocks (never exported)
// ===========================================================================
module ghost_modules() {
    %translate([pi_x0, pi_y0, pi_z + standoff_h])
        cube([pi_w, pi_l, 1.6]);                      // Pi board
    %translate([pi_x0, pi_y0, pi_z + standoff_h + 2])
        cube([pi_w, pi_l, hat_stack_h]);              // HAT stack
    %translate([ext_w/2 - vfd_mod_w/2, wall, vfd_cz - vfd_mod_h/2])
        cube([vfd_mod_w, vfd_mod_d, vfd_mod_h]);      // VFD module
    %translate([oled_cx - oled_mod_w/2, wall, oled_cz - oled_view_yoff - oled_mod_h/2])
        cube([oled_mod_w, 6, oled_mod_h]);            // OLED module
}

// ===========================================================================
// Output
// ===========================================================================
if (part == "base") {
    base();
} else if (part == "lid") {
    lid();
} else {
    base();
    translate([0, 0, ext_h + 12]) lid();
    if (preview_modules) ghost_modules();
}

// Echo the computed envelope so it prints in the OpenSCAD console.
echo(str("Exterior envelope (mm): ", ext_w, " W x ", ext_d, " D x ", ext_h, " H"));
echo(str("Interior (mm): ", inner_w, " x ", inner_d, " x ", inner_h));
