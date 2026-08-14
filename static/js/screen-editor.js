/**
 * Visual Screen Editor for OLED/VFD/LED Displays
 *
 * Schema-driven WYSIWYG editor. Every element type is described once in the
 * TYPES registry (defaults, property fields, canvas drawing, overlay bounds,
 * resize behaviour, and server (de)serialisation), so the palette, property
 * panel, layer list, canvas preview and save payload all stay in sync.
 *
 * Supported graphics:
 *   text, bar, rectangle, line, hline, vline, circle, arc, icon, gauge, clock
 *
 * The available tools are filtered per display type:
 *   - oled: full graphics set (monochrome 128x64 SSD1306)
 *   - vfd:  text + shapes the GU-7000 hardware can draw (140x32)
 *   - led:  text only (character-based sign)
 *
 * Editing niceties: undo/redo history, drag to move, corner handle to
 * resize, arrow-key nudging, snap-to-grid, per-display phosphor colours,
 * and live {now.*} variables in the preview.
 */

const ScreenEditor = (function() {
    'use strict';

    // Editor state
    const state = {
        displayType: 'oled',
        canvasWidth: 128,
        canvasHeight: 64,
        zoom: 4,
        elements: [],
        selectedElement: null,
        dataSources: [],
        isDragging: false,
        isResizing: false,
        dragElement: null,
        dragStartX: 0,
        dragStartY: 0,
        dragStartProps: null,
        dragMoved: false,
        screenId: null,
        activeDynamicInput: null,
        showGrid: false,
        snapOn: false,
        dirty: false,
        // LED only: false = legacy 4-line scrolling text (send_message()),
        // true = single-frame Dots/graphics mode (render_frame(), see
        // scripts/led_sign_controller.py's render_led_elements()).
        ledGraphicsMode: false
    };

    // Display dimensions by type. LED has two unrelated canvases: legacy
    // text mode has no real per-pixel addressing at all (it's 4 lines of
    // character-cell text; x/y here is purely an authoring convenience --
    // only line order round-trips, see buildTemplateData()), so it keeps
    // a virtual 80x32 grid. Graphics mode is the sign's real 160x16
    // Picture File (Dots) canvas -- pixel-accurate, matches
    // Alpha9120CController.MAX_DOTS_COLS/MAX_DOTS_ROWS.
    const DISPLAY_DIMS = {
        oled: { width: 128, height: 64 },
        vfd: { width: 140, height: 32 },
        led: { width: 80, height: 32 },
        'led-graphics': { width: 160, height: 16 }
    };

    // Which DISPLAY_DIMS/palette key applies right now.
    function paletteKey() {
        if (state.displayType === 'led') return state.ledGraphicsMode ? 'led-graphics' : 'led';
        return state.displayType;
    }

    function currentDisplayDims() {
        return DISPLAY_DIMS[paletteKey()];
    }

    // Phosphor colours so the preview looks like the real hardware
    const DISPLAY_THEMES = {
        oled: { pix: '#d4ecff', bg: '#01040a' },   // cool blue-white OLED
        vfd:  { pix: '#5dffc3', bg: '#001a12' },   // cyan-green VFD phosphor
        led:  { pix: '#ffb300', bg: '#140d00' }    // amber LED matrix
    };

    function theme() { return DISPLAY_THEMES[state.displayType] || DISPLAY_THEMES.oled; }

    // Font sizes (actual pixel heights)
    const FONT_SIZES = {
        small: 11,
        medium: 14,
        large: 18,
        xlarge: 28,
        huge: 36
    };

    const FONT_OPTIONS = [
        ['small', 'Small (11px)'],
        ['medium', 'Medium (14px)'],
        ['large', 'Large (18px)'],
        ['xlarge', 'X-Large (28px)'],
        ['huge', 'Huge (36px)']
    ];

    const ALIGN_OPTIONS = [['left', 'Left'], ['center', 'Center'], ['right', 'Right']];

    // LED sign options (mirror scripts/led_sign_controller.py enums)
    const LED_COLORS = ['AMBER', 'RED', 'GREEN', 'ORANGE', 'YELLOW', 'DIM_RED', 'DIM_GREEN',
        'BROWN', 'RAINBOW_1', 'RAINBOW_2', 'COLOR_MIX', 'AUTO_COLOR'];
    const LED_MODES = ['HOLD', 'ROTATE', 'FLASH', 'SCROLL', 'ROLL_LEFT', 'ROLL_RIGHT',
        'ROLL_UP', 'ROLL_DOWN', 'WIPE_LEFT', 'WIPE_RIGHT', 'AUTO_MODE'];
    const LED_SPEEDS = ['SPEED_1', 'SPEED_2', 'SPEED_3', 'SPEED_4', 'SPEED_5'];
    const LED_FONTS = ['FONT_5x7', 'FONT_6x7', 'FONT_7x9', 'FONT_8x7', 'FONT_7x11',
        'FONT_15x7', 'FONT_19x7', 'FONT_7x13', 'FONT_16x9', 'FONT_32x16'];

    // Built-in vector icons shared by all three display engines (mirrors
    // app_core/oled.py's _ICON_RENDERERS -- the single glyph set OLED, VFD
    // and LED graphics mode all draw from).
    const ICON_NAMES = [
        'antenna', 'speaker', 'warning', 'check', 'cross',
        'network', 'shield', 'wave', 'clock', 'heartbeat',
        'satellite', 'gps_pin', 'bolt'
    ];

    // Suggested {variable} names per endpoint for the data-source modal
    const ENDPOINT_VAR_SUGGESTIONS = {
        '/api/system_status': 'status',
        '/api/system_health': 'health',
        '/api/alerts': 'alerts',
        '/api/audio/metrics': 'audio',
        '/api/audio/metrics/latest': 'audio',
        '/api/audio/health': 'audio_health',
        '/api/eas-monitor/status': 'eas',
        '/api/hardware/gps/status': 'gps',
        '/api/monitoring/radio': 'radio',
        '/api/stream/status': 'stream',
        '/api/receivers': 'receivers'
    };

    // Canvas and context
    let canvas, ctx;

    // Undo/redo history (JSON snapshots of elements + data sources)
    let history = [];
    let historyIndex = -1;
    let nudgeCommitTimer = null;

    // ------------------------------------------------------------------
    // Small icon renderers for the canvas preview. These are intentionally
    // simple approximations of the device-side vector icons; the live device
    // renders the real glyphs.
    // ------------------------------------------------------------------
    const ICON_DRAW = {
        antenna(c, x, y, s) {
            const cx = x + s / 2;
            c.beginPath();
            c.moveTo(cx, y + s); c.lineTo(cx, y + s * 0.35);
            c.moveTo(x + s * 0.2, y + s); c.lineTo(cx, y + s * 0.6);
            c.lineTo(x + s * 0.8, y + s); c.stroke();
            c.beginPath(); c.arc(cx, y + s * 0.3, s * 0.18, Math.PI, 2 * Math.PI); c.stroke();
        },
        speaker(c, x, y, s) {
            c.beginPath();
            c.moveTo(x, y + s * 0.35); c.lineTo(x + s * 0.3, y + s * 0.35);
            c.lineTo(x + s * 0.55, y + s * 0.15); c.lineTo(x + s * 0.55, y + s * 0.85);
            c.lineTo(x + s * 0.3, y + s * 0.65); c.lineTo(x, y + s * 0.65); c.closePath(); c.stroke();
            c.beginPath(); c.arc(x + s * 0.55, y + s * 0.5, s * 0.3, -0.6, 0.6); c.stroke();
        },
        warning(c, x, y, s) {
            c.beginPath();
            c.moveTo(x + s / 2, y); c.lineTo(x + s, y + s); c.lineTo(x, y + s); c.closePath(); c.stroke();
            c.beginPath();
            c.moveTo(x + s / 2, y + s * 0.35); c.lineTo(x + s / 2, y + s * 0.65); c.stroke();
            c.fillRect(x + s / 2 - 0.5, y + s * 0.78, 1.5, 1.5);
        },
        check(c, x, y, s) {
            c.beginPath();
            c.moveTo(x + s * 0.15, y + s * 0.55); c.lineTo(x + s * 0.4, y + s * 0.8);
            c.lineTo(x + s * 0.85, y + s * 0.2); c.stroke();
        },
        cross(c, x, y, s) {
            c.beginPath();
            c.moveTo(x + s * 0.15, y + s * 0.15); c.lineTo(x + s * 0.85, y + s * 0.85);
            c.moveTo(x + s * 0.85, y + s * 0.15); c.lineTo(x + s * 0.15, y + s * 0.85); c.stroke();
        },
        network(c, x, y, s) {
            const pts = [[x + s * 0.2, y + s * 0.8], [x + s * 0.5, y + s * 0.2], [x + s * 0.8, y + s * 0.8]];
            c.beginPath();
            c.moveTo(pts[0][0], pts[0][1]); c.lineTo(pts[1][0], pts[1][1]); c.lineTo(pts[2][0], pts[2][1]); c.stroke();
            pts.forEach(p => { c.beginPath(); c.arc(p[0], p[1], s * 0.1, 0, 2 * Math.PI); c.fill(); });
        },
        shield(c, x, y, s) {
            c.beginPath();
            c.moveTo(x + s / 2, y); c.lineTo(x + s, y + s * 0.25);
            c.lineTo(x + s * 0.8, y + s); c.lineTo(x + s / 2, y + s * 0.85);
            c.lineTo(x + s * 0.2, y + s); c.lineTo(x, y + s * 0.25); c.closePath(); c.stroke();
        },
        wave(c, x, y, s) {
            c.beginPath();
            for (let i = 0; i <= s; i++) {
                const yy = y + s / 2 - Math.sin((i / s) * Math.PI * 2) * (s * 0.35);
                i === 0 ? c.moveTo(x + i, yy) : c.lineTo(x + i, yy);
            }
            c.stroke();
        },
        clock(c, x, y, s) {
            const cx = x + s / 2, cy = y + s / 2, r = s / 2 - 1;
            c.beginPath(); c.arc(cx, cy, r, 0, 2 * Math.PI); c.stroke();
            c.beginPath();
            c.moveTo(cx, cy); c.lineTo(cx, cy - r * 0.6);
            c.moveTo(cx, cy); c.lineTo(cx + r * 0.5, cy); c.stroke();
        },
        heartbeat(c, x, y, s) {
            const my = y + s / 2;
            c.beginPath();
            c.moveTo(x, my); c.lineTo(x + s * 0.3, my);
            c.lineTo(x + s * 0.45, y + s * 0.2); c.lineTo(x + s * 0.6, y + s * 0.85);
            c.lineTo(x + s * 0.72, my); c.lineTo(x + s, my); c.stroke();
        },
        satellite(c, x, y, s) {
            const cx = x + s / 2, cy = y + s / 2;
            const spoke = Math.max(2, s / 2);
            c.beginPath();
            c.moveTo(cx - spoke, cy - spoke); c.lineTo(cx + spoke, cy + spoke);
            c.moveTo(cx - spoke, cy + spoke); c.lineTo(cx + spoke, cy - spoke);
            c.stroke();
            c.beginPath(); c.arc(cx, cy, Math.max(1, s / 4), 0, 2 * Math.PI); c.fill();
        },
        gps_pin(c, x, y, s) {
            const cx = x + s / 2, r = Math.max(1, s / 2 - 1), topCy = y + r;
            c.beginPath(); c.arc(cx, topCy, r, 0, 2 * Math.PI); c.stroke();
            c.beginPath();
            c.moveTo(cx - r / 2, topCy + r - 1); c.lineTo(cx + r / 2, topCy + r - 1);
            c.lineTo(cx, y + s - 1); c.closePath(); c.fill();
        },
        bolt(c, x, y, s) {
            c.beginPath();
            c.moveTo(x + s * 0.6, y);
            c.lineTo(x + s * 0.2, y + s * 0.6);
            c.lineTo(x + s * 0.5, y + s * 0.6);
            c.lineTo(x + s * 0.4, y + s - 1);
            c.lineTo(x + s * 0.8, y + s * 0.4);
            c.lineTo(x + s * 0.5, y + s * 0.4);
            c.closePath();
            c.fill();
        }
    };

    // Substitute built-in {now.*} variables so clocks/dates look real in the
    // editor preview. Data-source variables are left verbatim so the user can
    // see which fields are dynamic.
    function previewText(text) {
        if (!text || text.indexOf('{now.') === -1) return text;
        const now = new Date();
        const pad = n => String(n).padStart(2, '0');
        const h12 = now.getHours() % 12 || 12;
        const ampm = now.getHours() >= 12 ? 'PM' : 'AM';
        const vars = {
            'now.time': `${pad(h12)}:${pad(now.getMinutes())} ${ampm}`,
            'now.time_24': `${pad(now.getHours())}:${pad(now.getMinutes())}`,
            'now.date': `${pad(now.getMonth() + 1)}/${pad(now.getDate())}/${now.getFullYear()}`
        };
        vars['now.datetime'] = `${vars['now.date']} ${vars['now.time']}`;
        return text.replace(/\{(now\.[a-z_0-9]+)\}/g, (m, key) => vars[key] !== undefined ? vars[key] : m);
    }

    // ------------------------------------------------------------------
    // Property-field helpers
    // ------------------------------------------------------------------
    function posFields() {
        return [
            { key: 'x', label: 'X', kind: 'number', col: 6 },
            { key: 'y', label: 'Y', kind: 'number', col: 6 }
        ];
    }

    function fontField() {
        return { key: 'font', label: 'Font Size', kind: 'select', options: FONT_OPTIONS };
    }

    // VFD/LED-graphics text only recognises a literal font value of
    // "large" (their 14pt/15pt bold hero size) -- anything else, including
    // OLED's small/medium/xlarge/huge names, falls through to the same
    // flat default size on those two engines (scripts/vfd_controller.py's
    // and scripts/led_sign_controller.py's render_*_elements()). Offering
    // OLED's 5-size list there would let an operator "pick" a size that
    // has no effect on the real device.
    const VFD_LED_FONT_OPTIONS = [['', 'Normal'], ['large', 'Large (Hero)']];

    function fontOptionsForDisplay() {
        return state.displayType === 'oled' ? FONT_OPTIONS : VFD_LED_FONT_OPTIONS;
    }

    // ------------------------------------------------------------------
    // Element type registry
    //   create()        -> default props (id added by caller)
    //   fields          -> property panel schema
    //   draw(el)        -> render onto the canvas (phosphor-on-black preview)
    //   bounds(el)      -> {x, y, w, h} top-left overlay box
    //   resize(el, start, dx, dy, snap) -> apply corner-handle resize (optional)
    //   toTemplate(el)  -> server JSON
    //   fromTemplate(t) -> editor props (id added by caller)
    //   layerLabel(el)  -> short label for the layers list
    //   displays        -> which display types may add this element
    // ------------------------------------------------------------------
    const TYPES = {
        text: {
            label: 'Text', icon: 'fa-font', displays: ['oled', 'vfd', 'led', 'led-graphics'],
            create: () => ({ type: 'text', text: 'New Text', x: 4, y: 4, font: 'small',
                align: 'left', maxWidth: null, wrap: true, invert: false, allowEmpty: false }),
            fields: [
                { key: 'text', label: 'Text Content', kind: 'text', dynamic: true,
                    placeholder: '{variable} or Static Text', help: 'Use {variable} for dynamic data' },
                fontField(),
                ...posFields(),
                { key: 'align', label: 'Align', kind: 'select', options: ALIGN_OPTIONS },
                { key: 'maxWidth', label: 'Max Width (px)', kind: 'number', allowNull: true, placeholder: 'Auto' },
                { key: 'wrap', label: 'Word Wrap', kind: 'checkbox' },
                { key: 'invert', label: 'Invert Colors', kind: 'checkbox' },
                { key: 'allowEmpty', label: 'Allow Empty', kind: 'checkbox' }
            ],
            draw(el) {
                const fontSize = FONT_SIZES[el.font] || 11;
                ctx.font = `${fontSize}px monospace`;
                ctx.textBaseline = 'top';
                const txt = previewText(el.text || '');
                const w = Math.max(2, ctx.measureText(txt).width);
                let x = el.x;
                if (el.align === 'right') x = el.x - w;
                else if (el.align === 'center') x = el.x - w / 2;
                if (el.invert) {
                    ctx.fillStyle = theme().pix;
                    ctx.fillRect(x - 1, el.y - 1, w + 2, fontSize + 2);
                    ctx.fillStyle = theme().bg;
                } else {
                    ctx.fillStyle = theme().pix;
                }
                ctx.fillText(txt, x, el.y);
            },
            bounds(el) {
                const fontSize = FONT_SIZES[el.font] || 11;
                ctx.font = `${fontSize}px monospace`;
                const w = Math.max(10, ctx.measureText(previewText(el.text || '')).width);
                let x = el.x;
                if (el.align === 'right') x = el.x - w;
                else if (el.align === 'center') x = el.x - w / 2;
                return { x, y: el.y, w, h: fontSize };
            },
            toTemplate: el => ({ type: 'text', text: el.text, x: el.x, y: el.y, font: el.font,
                align: el.align || 'left', max_width: el.maxWidth || null,
                wrap: el.wrap, invert: el.invert || null, allow_empty: el.allowEmpty || false }),
            fromTemplate: t => ({ type: 'text', text: t.text || '', x: t.x || 0, y: t.y || 0,
                font: t.font || 'small', align: t.align || 'left', maxWidth: t.max_width || null,
                wrap: t.wrap !== false, invert: !!t.invert, allowEmpty: !!t.allow_empty }),
            layerLabel: el => el.text || '(empty)'
        },

        bar: {
            label: 'Bar', icon: 'fa-chart-bar', displays: ['oled', 'vfd', 'led-graphics'],
            create: () => ({ type: 'bar', x: 4, y: 10, width: 80, height: 9,
                value: '50', border: true, preview: 60 }),
            fields: [
                { key: 'value', label: 'Value (0–100 or {variable})', kind: 'text', dynamic: true,
                    placeholder: '{status.system_resources.cpu_usage_percent}',
                    help: 'Template variable resolves to 0–100' },
                ...posFields(),
                { key: 'width', label: 'Width (px)', kind: 'number', col: 6, min: 4 },
                { key: 'height', label: 'Height (px)', kind: 'number', col: 6, min: 3 },
                { key: 'preview', label: 'Preview Fill', kind: 'range', min: 0, max: 100, unit: '%',
                    help: 'Canvas preview only — live data used on device' },
                { key: 'border', label: 'Show Border', kind: 'checkbox' }
            ],
            draw(el) {
                const w = Math.max(4, el.width), h = Math.max(3, el.height);
                const pct = clamp(el.preview != null ? el.preview : 60, 0, 100);
                ctx.strokeStyle = theme().pix; ctx.fillStyle = theme().pix; ctx.lineWidth = 1;
                if (el.border !== false) {
                    ctx.strokeRect(el.x + 0.5, el.y + 0.5, w - 1, h - 1);
                    const inner = Math.floor((pct / 100) * (w - 2));
                    if (inner > 0) ctx.fillRect(el.x + 1, el.y + 1, inner, h - 2);
                } else {
                    const filled = Math.floor((pct / 100) * w);
                    if (filled > 0) ctx.fillRect(el.x, el.y, filled, h);
                }
            },
            bounds: el => ({ x: el.x, y: el.y, w: Math.max(4, el.width), h: Math.max(3, el.height) }),
            resize(el, start, dx, dy, snap) {
                el.width = Math.max(4, snap(start.width + dx));
                el.height = Math.max(3, snap(start.height + dy));
            },
            toTemplate: el => ({ type: 'bar', x: el.x, y: el.y, width: el.width,
                height: el.height, value: el.value || '0', border: el.border !== false }),
            fromTemplate: t => ({ type: 'bar', x: t.x || 0, y: t.y || 0, width: t.width || 80,
                height: t.height || 9, value: t.value != null ? String(t.value) : '50',
                border: t.border !== false, preview: 60 }),
            layerLabel: el => `Bar ${el.width}×${el.height}`
        },

        rectangle: {
            label: 'Rect', icon: 'fa-square', displays: ['oled', 'vfd', 'led-graphics'],
            create: () => ({ type: 'rectangle', x: 4, y: 4, width: 30, height: 20, filled: false }),
            fields: [
                ...posFields(),
                { key: 'width', label: 'Width (px)', kind: 'number', col: 6, min: 1 },
                { key: 'height', label: 'Height (px)', kind: 'number', col: 6, min: 1 },
                { key: 'filled', label: 'Filled', kind: 'checkbox' }
            ],
            draw(el) {
                const w = Math.max(1, el.width), h = Math.max(1, el.height);
                ctx.strokeStyle = theme().pix; ctx.fillStyle = theme().pix; ctx.lineWidth = 1;
                if (el.filled) ctx.fillRect(el.x, el.y, w, h);
                else ctx.strokeRect(el.x + 0.5, el.y + 0.5, w - 1, h - 1);
            },
            bounds: el => ({ x: el.x, y: el.y, w: Math.max(1, el.width), h: Math.max(1, el.height) }),
            resize(el, start, dx, dy, snap) {
                el.width = Math.max(1, snap(start.width + dx));
                el.height = Math.max(1, snap(start.height + dy));
            },
            toTemplate: el => ({ type: 'rectangle', x: el.x, y: el.y, width: el.width,
                height: el.height, filled: !!el.filled }),
            fromTemplate: t => ({ type: 'rectangle', x: t.x || 0, y: t.y || 0, width: t.width || 30,
                height: t.height || 20, filled: !!t.filled }),
            layerLabel: el => `Rect ${el.width}×${el.height}`
        },

        line: {
            label: 'Line', icon: 'fa-slash', displays: ['oled', 'vfd'],
            create: () => ({ type: 'line', x1: 4, y1: 4, x2: 40, y2: 24, lineWidth: 1 }),
            fields: [
                { key: 'x1', label: 'X1', kind: 'number', col: 6 },
                { key: 'y1', label: 'Y1', kind: 'number', col: 6 },
                { key: 'x2', label: 'X2', kind: 'number', col: 6 },
                { key: 'y2', label: 'Y2', kind: 'number', col: 6 },
                { key: 'lineWidth', label: 'Thickness (px)', kind: 'number', min: 1 }
            ],
            draw(el) {
                ctx.strokeStyle = theme().pix;
                ctx.lineWidth = Math.max(1, el.lineWidth || 1);
                ctx.beginPath();
                ctx.moveTo(el.x1 + 0.5, el.y1 + 0.5);
                ctx.lineTo(el.x2 + 0.5, el.y2 + 0.5);
                ctx.stroke();
            },
            bounds: el => ({ x: Math.min(el.x1, el.x2), y: Math.min(el.y1, el.y2),
                w: Math.max(2, Math.abs(el.x2 - el.x1)), h: Math.max(2, Math.abs(el.y2 - el.y1)) }),
            resize(el, start, dx, dy, snap) {
                el.x2 = snap(start.x2 + dx);
                el.y2 = snap(start.y2 + dy);
            },
            toTemplate: el => ({ type: 'line', x1: el.x1, y1: el.y1, x2: el.x2, y2: el.y2,
                width: el.lineWidth || 1 }),
            fromTemplate: t => ({ type: 'line', x1: t.x1 || 0, y1: t.y1 || 0, x2: t.x2 || 0,
                y2: t.y2 || 0, lineWidth: t.width || 1 }),
            layerLabel: el => `Line (${el.x1},${el.y1})→(${el.x2},${el.y2})`
        },

        hline: {
            label: 'H-Divider', icon: 'fa-grip-lines', displays: ['oled', 'vfd', 'led-graphics'],
            create: () => ({ type: 'hline', x: 0, y: 16, width: 64, dotted: false }),
            fields: [
                ...posFields(),
                { key: 'width', label: 'Width (px)', kind: 'number', min: 1 },
                { key: 'dotted', label: 'Dotted', kind: 'checkbox' }
            ],
            draw(el) {
                ctx.strokeStyle = theme().pix; ctx.fillStyle = theme().pix; ctx.lineWidth = 1;
                const w = Math.max(1, el.width);
                if (el.dotted) {
                    for (let px = 0; px < w; px += 2) ctx.fillRect(el.x + px, el.y, 1, 1);
                } else {
                    ctx.beginPath();
                    ctx.moveTo(el.x, el.y + 0.5); ctx.lineTo(el.x + w, el.y + 0.5); ctx.stroke();
                }
            },
            bounds: el => ({ x: el.x, y: el.y - 2, w: Math.max(1, el.width), h: 5 }),
            resize(el, start, dx, dy, snap) {
                el.width = Math.max(1, snap(start.width + dx));
            },
            toTemplate: el => ({ type: el.dotted ? 'dotted_hline' : 'hline', x: el.x, y: el.y, width: el.width }),
            fromTemplate: t => ({ type: 'hline', x: t.x || 0, y: t.y || 0, width: t.width || 64,
                dotted: t.type === 'dotted_hline' }),
            layerLabel: el => `${el.dotted ? 'Dotted ' : ''}H-Line ${el.width}px`
        },

        vline: {
            label: 'V-Divider', icon: 'fa-grip-lines-vertical', displays: ['oled', 'vfd', 'led-graphics'],
            create: () => ({ type: 'vline', x: 16, y: 0, height: 32 }),
            fields: [
                ...posFields(),
                { key: 'height', label: 'Height (px)', kind: 'number', min: 1 }
            ],
            draw(el) {
                ctx.strokeStyle = theme().pix; ctx.lineWidth = 1;
                const h = Math.max(1, el.height);
                ctx.beginPath();
                ctx.moveTo(el.x + 0.5, el.y); ctx.lineTo(el.x + 0.5, el.y + h); ctx.stroke();
            },
            bounds: el => ({ x: el.x - 2, y: el.y, w: 5, h: Math.max(1, el.height) }),
            resize(el, start, dx, dy, snap) {
                el.height = Math.max(1, snap(start.height + dy));
            },
            toTemplate: el => ({ type: 'vline', x: el.x, y: el.y, height: el.height }),
            fromTemplate: t => ({ type: 'vline', x: t.x || 0, y: t.y || 0, height: t.height || 32 }),
            layerLabel: el => `V-Line ${el.height}px`
        },

        circle: {
            label: 'Circle', icon: 'fa-circle', displays: ['oled', 'vfd'],
            create: () => ({ type: 'circle', x: 32, y: 32, radius: 12, filled: false }),
            fields: [
                { key: 'x', label: 'Center X', kind: 'number', col: 6 },
                { key: 'y', label: 'Center Y', kind: 'number', col: 6 },
                { key: 'radius', label: 'Radius (px)', kind: 'number', min: 1 },
                { key: 'filled', label: 'Filled', kind: 'checkbox' }
            ],
            draw(el) {
                ctx.strokeStyle = theme().pix; ctx.fillStyle = theme().pix; ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.arc(el.x, el.y, Math.max(1, el.radius), 0, 2 * Math.PI);
                if (el.filled) ctx.fill(); else ctx.stroke();
            },
            bounds: el => ({ x: el.x - el.radius, y: el.y - el.radius, w: el.radius * 2, h: el.radius * 2 }),
            resize(el, start, dx, dy, snap) {
                el.radius = Math.max(1, snap(start.radius + Math.round((dx + dy) / 2)));
            },
            toTemplate: el => ({ type: 'circle', x: el.x, y: el.y, radius: el.radius, filled: !!el.filled }),
            fromTemplate: t => ({ type: 'circle', x: t.x || 32, y: t.y || 32, radius: t.radius || 12,
                filled: !!t.filled }),
            layerLabel: el => `Circle r${el.radius}`
        },

        arc: {
            label: 'Arc', icon: 'fa-circle-notch', displays: ['oled'],
            create: () => ({ type: 'arc', x: 32, y: 32, radius: 14, start: 0, end: 180 }),
            fields: [
                { key: 'x', label: 'Center X', kind: 'number', col: 6 },
                { key: 'y', label: 'Center Y', kind: 'number', col: 6 },
                { key: 'radius', label: 'Radius (px)', kind: 'number', min: 1 },
                { key: 'start', label: 'Start °', kind: 'number', col: 6 },
                { key: 'end', label: 'End °', kind: 'number', col: 6 }
            ],
            draw(el) {
                ctx.strokeStyle = theme().pix; ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.arc(el.x, el.y, Math.max(1, el.radius),
                    (el.start || 0) * Math.PI / 180, (el.end || 0) * Math.PI / 180);
                ctx.stroke();
            },
            bounds: el => ({ x: el.x - el.radius, y: el.y - el.radius, w: el.radius * 2, h: el.radius * 2 }),
            resize(el, start, dx, dy, snap) {
                el.radius = Math.max(1, snap(start.radius + Math.round((dx + dy) / 2)));
            },
            toTemplate: el => ({ type: 'arc', x: el.x, y: el.y, radius: el.radius, start: el.start, end: el.end }),
            fromTemplate: t => ({ type: 'arc', x: t.x || 32, y: t.y || 32, radius: t.radius || 14,
                start: t.start || 0, end: t.end != null ? t.end : 180 }),
            layerLabel: el => `Arc ${el.start}–${el.end}°`
        },

        icon: {
            label: 'Icon', icon: 'fa-icons', displays: ['oled', 'vfd', 'led-graphics'],
            create: () => ({ type: 'icon', name: 'antenna', x: 4, y: 4, size: 16 }),
            fields: [
                { key: 'name', label: 'Icon', kind: 'select', options: ICON_NAMES.map(n => [n, n]) },
                ...posFields(),
                { key: 'size', label: 'Size (px)', kind: 'number', min: 6 }
            ],
            draw(el) {
                ctx.strokeStyle = theme().pix; ctx.fillStyle = theme().pix; ctx.lineWidth = 1;
                const fn = ICON_DRAW[el.name];
                if (fn) fn(ctx, el.x, el.y, Math.max(6, el.size));
                else ctx.strokeRect(el.x + 0.5, el.y + 0.5, el.size - 1, el.size - 1);
            },
            bounds: el => ({ x: el.x, y: el.y, w: Math.max(6, el.size), h: Math.max(6, el.size) }),
            resize(el, start, dx, dy, snap) {
                el.size = Math.max(6, snap(start.size + Math.max(dx, dy)));
            },
            toTemplate: el => ({ type: 'icon', name: el.name, x: el.x, y: el.y, size: el.size }),
            fromTemplate: t => ({ type: 'icon', name: t.name || 'antenna', x: t.x || 0, y: t.y || 0,
                size: t.size || 16 }),
            layerLabel: el => `Icon: ${el.name}`
        },

        gauge: {
            label: 'Gauge', icon: 'fa-gauge-high', displays: ['oled', 'vfd'],
            create: () => ({ type: 'gauge', x: 64, y: 48, radius: 24, value: '50', preview: 60 }),
            fields: [
                { key: 'value', label: 'Value (0–100 or {variable})', kind: 'text', dynamic: true,
                    placeholder: '{status.system_resources.cpu_usage_percent}' },
                { key: 'x', label: 'Center X', kind: 'number', col: 6 },
                { key: 'y', label: 'Center Y', kind: 'number', col: 6 },
                { key: 'radius', label: 'Radius (px)', kind: 'number', min: 8 },
                { key: 'preview', label: 'Preview Value', kind: 'range', min: 0, max: 100,
                    help: 'Canvas preview only — live data used on device' }
            ],
            draw(el) {
                ctx.strokeStyle = theme().pix; ctx.fillStyle = theme().pix; ctx.lineWidth = 1;
                const r = Math.max(8, el.radius);
                ctx.beginPath(); ctx.arc(el.x, el.y, r, Math.PI, 2 * Math.PI); ctx.stroke();
                const pct = clamp(el.preview != null ? el.preview : 60, 0, 100);
                const ang = Math.PI + (pct / 100) * Math.PI;
                ctx.beginPath();
                ctx.moveTo(el.x, el.y);
                ctx.lineTo(el.x + Math.cos(ang) * r * 0.7, el.y + Math.sin(ang) * r * 0.7);
                ctx.stroke();
                ctx.beginPath(); ctx.arc(el.x, el.y, 1.5, 0, 2 * Math.PI); ctx.fill();
            },
            bounds: el => ({ x: el.x - el.radius, y: el.y - el.radius, w: el.radius * 2, h: el.radius + 4 }),
            resize(el, start, dx, dy, snap) {
                el.radius = Math.max(8, snap(start.radius + Math.round((dx + dy) / 2)));
            },
            toTemplate: el => ({ type: 'gauge', x: el.x, y: el.y, radius: el.radius, value: el.value || '0' }),
            fromTemplate: t => ({ type: 'gauge', x: t.x || 64, y: t.y || 48, radius: t.radius || 24,
                value: t.value != null ? String(t.value) : '50', preview: 60 }),
            layerLabel: el => `Gauge r${el.radius}`
        },

        compass: {
            label: 'Compass', icon: 'fa-compass', displays: ['oled', 'vfd'],
            create: () => ({ type: 'compass', x: 30, y: 30, radius: 20, heading: '{gps.track_angle}', preview: 45 }),
            fields: [
                { key: 'heading', label: 'Heading ° (0–360 or {variable})', kind: 'text', dynamic: true,
                    placeholder: '{gps.track_angle}', help: 'Leave empty for a bare dial (no fix yet)' },
                { key: 'x', label: 'Center X', kind: 'number', col: 6 },
                { key: 'y', label: 'Center Y', kind: 'number', col: 6 },
                { key: 'radius', label: 'Radius (px)', kind: 'number', min: 8 },
                { key: 'preview', label: 'Preview Heading', kind: 'range', min: 0, max: 360,
                    help: 'Canvas preview only — live data used on device' }
            ],
            draw(el) {
                ctx.strokeStyle = theme().pix; ctx.fillStyle = theme().pix; ctx.lineWidth = 1;
                const r = Math.max(8, el.radius), cx = el.x, cy = el.y;
                ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2 * Math.PI); ctx.stroke();
                // Cardinal ticks and labels sit OUTSIDE the ring so they
                // never collide with the needle (mirrors the device-side
                // fix for this in app_core/oled.py's render_frame()).
                const fontSize = Math.max(6, Math.round(r * 0.28));
                ctx.font = `${fontSize}px monospace`;
                ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
                [[0, 'N'], [90, 'E'], [180, 'S'], [270, 'W']].forEach(([deg, label]) => {
                    const a = (deg - 90) * Math.PI / 180;
                    const tx1 = cx + Math.cos(a) * (r - 3), ty1 = cy + Math.sin(a) * (r - 3);
                    const tx2 = cx + Math.cos(a) * (r - 1), ty2 = cy + Math.sin(a) * (r - 1);
                    ctx.beginPath(); ctx.moveTo(tx1, ty1); ctx.lineTo(tx2, ty2); ctx.stroke();
                    ctx.fillText(label, cx + Math.cos(a) * (r + 7), cy + Math.sin(a) * (r + 7));
                });
                ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
                const heading = el.preview != null ? el.preview : 45;
                const a = (heading - 90) * Math.PI / 180;
                const len = r * 0.68;
                ctx.beginPath();
                ctx.moveTo(cx, cy);
                ctx.lineTo(cx + Math.cos(a) * len, cy + Math.sin(a) * len);
                ctx.stroke();
                ctx.beginPath(); ctx.arc(cx, cy, 1.5, 0, 2 * Math.PI); ctx.fill();
            },
            bounds: el => ({ x: el.x - el.radius - 10, y: el.y - el.radius - 10,
                w: (el.radius + 10) * 2, h: (el.radius + 10) * 2 }),
            resize(el, start, dx, dy, snap) {
                el.radius = Math.max(8, snap(start.radius + Math.round((dx + dy) / 2)));
            },
            toTemplate: el => ({ type: 'compass', x: el.x, y: el.y, radius: el.radius, heading: el.heading || null }),
            fromTemplate: t => ({ type: 'compass', x: t.x || 30, y: t.y || 30, radius: t.radius || 20,
                heading: t.heading != null ? String(t.heading) : '', preview: 45 }),
            layerLabel: el => `Compass r${el.radius}`
        },

        segments: {
            label: 'Segments', icon: 'fa-grip-lines', displays: ['vfd'],
            create: () => ({ type: 'segments', x: 4, y: 10, width: 100, height: 8,
                value: '50', count: 14, gap: 2, preview: 60 }),
            fields: [
                { key: 'value', label: 'Value (0–100 or {variable})', kind: 'text', dynamic: true,
                    placeholder: '{audio.peak_level_percent}' },
                ...posFields(),
                { key: 'width', label: 'Width (px)', kind: 'number', col: 6, min: 4 },
                { key: 'height', label: 'Height (px)', kind: 'number', col: 6, min: 3 },
                { key: 'count', label: 'Segment Count', kind: 'number', col: 6, min: 2 },
                { key: 'gap', label: 'Gap (px)', kind: 'number', col: 6, min: 0 },
                { key: 'preview', label: 'Preview Fill', kind: 'range', min: 0, max: 100, unit: '%',
                    help: 'Canvas preview only — live data used on device' }
            ],
            draw(el) {
                const w = Math.max(4, el.width), h = Math.max(3, el.height);
                const count = Math.max(2, el.count || 14);
                const gap = Math.max(0, el.gap != null ? el.gap : 2);
                const segW = Math.max(1, (w - gap * (count - 1)) / count);
                const pct = clamp(el.preview != null ? el.preview : 60, 0, 100);
                const lit = Math.round((pct / 100) * count);
                ctx.strokeStyle = theme().pix; ctx.fillStyle = theme().pix; ctx.lineWidth = 1;
                let cx = el.x;
                for (let i = 0; i < count; i++) {
                    if (i < lit) ctx.fillRect(cx, el.y, segW, h);
                    else ctx.strokeRect(cx + 0.5, el.y + 0.5, segW - 1, h - 1);
                    cx += segW + gap;
                }
            },
            bounds: el => ({ x: el.x, y: el.y, w: Math.max(4, el.width), h: Math.max(3, el.height) }),
            resize(el, start, dx, dy, snap) {
                el.width = Math.max(4, snap(start.width + dx));
                el.height = Math.max(3, snap(start.height + dy));
            },
            toTemplate: el => ({ type: 'segments', x: el.x, y: el.y, width: el.width, height: el.height,
                value: el.value || '0', count: el.count || 14, gap: el.gap != null ? el.gap : 2 }),
            fromTemplate: t => ({ type: 'segments', x: t.x || 0, y: t.y || 0, width: t.width || 100,
                height: t.height || 8, value: t.value != null ? String(t.value) : '50',
                count: t.count || 14, gap: t.gap != null ? t.gap : 2, preview: 60 }),
            layerLabel: el => `Segments ${el.count || 14}`
        },

        clock: {
            label: 'Clock', icon: 'fa-clock', displays: ['oled'],
            create: () => ({ type: 'clock', x: 32, y: 32, radius: 28, showSeconds: false, showTicks: true }),
            fields: [
                { key: 'x', label: 'Center X', kind: 'number', col: 6 },
                { key: 'y', label: 'Center Y', kind: 'number', col: 6 },
                { key: 'radius', label: 'Radius (px)', kind: 'number', min: 8 },
                { key: 'showTicks', label: 'Hour Ticks', kind: 'checkbox' },
                { key: 'showSeconds', label: 'Second Hand', kind: 'checkbox' }
            ],
            draw(el) {
                ctx.strokeStyle = theme().pix; ctx.fillStyle = theme().pix; ctx.lineWidth = 1;
                const r = Math.max(8, el.radius), cx = el.x, cy = el.y;
                ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2 * Math.PI); ctx.stroke();
                if (el.showTicks) {
                    for (let h = 0; h < 12; h++) {
                        const a = (h * 30 - 90) * Math.PI / 180;
                        const ir = r - (h % 3 === 0 ? 4 : 2), or = r - 1;
                        ctx.beginPath();
                        ctx.moveTo(cx + Math.cos(a) * ir, cy + Math.sin(a) * ir);
                        ctx.lineTo(cx + Math.cos(a) * or, cy + Math.sin(a) * or);
                        ctx.stroke();
                    }
                }
                const now = new Date();
                const ha = ((now.getHours() % 12) + now.getMinutes() / 60) * 30 - 90;
                const ma = (now.getMinutes() + now.getSeconds() / 60) * 6 - 90;
                drawHand(cx, cy, ha, r * 0.5, 2);
                drawHand(cx, cy, ma, r * 0.78, 1);
                if (el.showSeconds) drawHand(cx, cy, now.getSeconds() * 6 - 90, r * 0.85, 1);
                ctx.beginPath(); ctx.arc(cx, cy, 1.5, 0, 2 * Math.PI); ctx.fill();
            },
            bounds: el => ({ x: el.x - el.radius, y: el.y - el.radius, w: el.radius * 2, h: el.radius * 2 }),
            resize(el, start, dx, dy, snap) {
                el.radius = Math.max(8, snap(start.radius + Math.round((dx + dy) / 2)));
            },
            toTemplate: el => ({ type: 'clock', x: el.x, y: el.y, radius: el.radius,
                show_seconds: !!el.showSeconds, show_ticks: el.showTicks !== false }),
            fromTemplate: t => ({ type: 'clock', x: t.x || 32, y: t.y || 32, radius: t.radius || 28,
                showSeconds: !!t.show_seconds, showTicks: t.show_ticks !== false }),
            layerLabel: el => `Clock r${el.radius}`
        }
    };

    function drawHand(cx, cy, angleDeg, len, width) {
        const a = angleDeg * Math.PI / 180;
        ctx.lineWidth = width;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(a) * len, cy + Math.sin(a) * len);
        ctx.stroke();
    }

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    function snapValue(v) {
        if (!state.snapOn) return v;
        return Math.round(v / 4) * 4;
    }

    function typeDef(el) { return TYPES[el.type] || TYPES.text; }

    // ------------------------------------------------------------------
    // Undo / redo history
    // ------------------------------------------------------------------
    function snapshot() {
        return JSON.stringify({ elements: state.elements, dataSources: state.dataSources });
    }

    function resetHistory() {
        history = [snapshot()];
        historyIndex = 0;
        updateUndoRedoButtons();
    }

    // Record the current state as an undo step and mark the screen dirty.
    function commit() {
        const snap = snapshot();
        if (history[historyIndex] === snap) return;
        history = history.slice(0, historyIndex + 1);
        history.push(snap);
        if (history.length > 60) history.shift();
        historyIndex = history.length - 1;
        updateUndoRedoButtons();
        markDirty();
    }

    function restoreSnapshot(snap) {
        const data = JSON.parse(snap);
        state.elements = data.elements || [];
        state.dataSources = data.dataSources || [];
        if (state.selectedElement && !getElementById(state.selectedElement)) {
            state.selectedElement = null;
            hideElementProps();
        } else if (state.selectedElement) {
            showElementProps(getElementById(state.selectedElement));
        }
        updateLayers();
        updateDataSourcesList();
        render();
        markDirty();
    }

    function undo() {
        if (historyIndex <= 0) return;
        historyIndex--;
        restoreSnapshot(history[historyIndex]);
        updateUndoRedoButtons();
    }

    function redo() {
        if (historyIndex >= history.length - 1) return;
        historyIndex++;
        restoreSnapshot(history[historyIndex]);
        updateUndoRedoButtons();
    }

    function updateUndoRedoButtons() {
        const undoBtn = document.getElementById('btn-undo');
        const redoBtn = document.getElementById('btn-redo');
        if (undoBtn) undoBtn.disabled = historyIndex <= 0;
        if (redoBtn) redoBtn.disabled = historyIndex >= history.length - 1;
    }

    function markDirty() {
        state.dirty = true;
    }

    // ------------------------------------------------------------------
    // Toast notifications (non-blocking replacement for alert())
    // ------------------------------------------------------------------
    function toast(message, kind) {
        const el = document.createElement('div');
        el.className = `editor-toast editor-toast-${kind || 'success'}`;
        el.textContent = message;
        document.body.appendChild(el);
        requestAnimationFrame(() => el.classList.add('show'));
        setTimeout(() => {
            el.classList.remove('show');
            setTimeout(() => el.remove(), 300);
        }, 2800);
    }

    // ------------------------------------------------------------------
    // Initialisation
    // ------------------------------------------------------------------
    function init() {
        canvas = document.getElementById('display-canvas');
        ctx = canvas.getContext('2d');

        const screenIdInput = document.getElementById('screen-id');
        if (screenIdInput && screenIdInput.value) {
            state.screenId = parseInt(screenIdInput.value);
        }

        populateLedSelects();
        setupEventListeners();
        updateCanvasDimensions();
        updateDisplayPanels();
        rebuildPalette();
        resetHistory();
        render();
    }

    function populateLedSelects() {
        const fill = (id, options, def) => {
            const sel = document.getElementById(id);
            if (!sel || sel.options.length) return;
            sel.innerHTML = options.map(o =>
                `<option value="${o}" ${o === def ? 'selected' : ''}>${o.replace(/_/g, ' ')}</option>`).join('');
        };
        fill('led-color', LED_COLORS, 'AMBER');
        fill('led-mode', LED_MODES, 'HOLD');
        fill('led-speed', LED_SPEEDS, 'SPEED_3');
        fill('led-font', LED_FONTS, 'FONT_7x9');
    }

    function setupEventListeners() {
        document.getElementById('display-type').addEventListener('change', function() {
            state.displayType = this.value;
            if (state.displayType !== 'led') state.ledGraphicsMode = false;
            updateCanvasDimensions();
            updateDisplayPanels();
            rebuildPalette();
            render();
            markDirty();
        });

        // Element palette buttons (delegated)
        const palette = document.getElementById('element-palette');
        if (palette) {
            palette.addEventListener('click', function(e) {
                const btn = e.target.closest('.palette-btn');
                if (btn) addElement(btn.dataset.type);
            });
        }

        document.getElementById('btn-clear-canvas').addEventListener('click', () => {
            if (confirm('Clear all elements?')) {
                state.elements = [];
                state.selectedElement = null;
                render();
                updateLayers();
                hideElementProps();
                commit();
            }
        });

        document.getElementById('btn-zoom-in').addEventListener('click', () => changeZoom(1));
        document.getElementById('btn-zoom-out').addEventListener('click', () => changeZoom(-1));

        const gridBtn = document.getElementById('btn-toggle-grid');
        if (gridBtn) {
            gridBtn.addEventListener('click', () => {
                state.showGrid = !state.showGrid;
                gridBtn.classList.toggle('active', state.showGrid);
                updateGridOverlay();
            });
        }

        const snapBtn = document.getElementById('btn-toggle-snap');
        if (snapBtn) {
            snapBtn.addEventListener('click', () => {
                state.snapOn = !state.snapOn;
                snapBtn.classList.toggle('active', state.snapOn);
            });
        }

        document.getElementById('btn-undo')?.addEventListener('click', undo);
        document.getElementById('btn-redo')?.addEventListener('click', redo);

        // Element actions (single shared panel)
        document.getElementById('btn-delete-element').addEventListener('click', deleteSelectedElement);
        document.getElementById('btn-duplicate-element').addEventListener('click', duplicateSelectedElement);

        // Delegated property field changes: 'input' updates live, 'change'
        // (blur / commit) records an undo step.
        document.getElementById('element-props-fields').addEventListener('input', onFieldChange);
        document.getElementById('element-props-fields').addEventListener('change', e => {
            onFieldChange(e);
            commit();
        });

        // Scroll effect controls
        document.getElementById('scroll-effect').addEventListener('change', function() {
            const needsSpeed = !['static', 'fade_in'].includes(this.value);
            document.getElementById('scroll-speed-group').style.display = needsSpeed ? 'block' : 'none';
            document.getElementById('scroll-fps-group').style.display = needsSpeed ? 'block' : 'none';
            markDirty();
        });
        document.getElementById('scroll-speed').addEventListener('input', function() {
            document.getElementById('scroll-speed-value').textContent = this.value;
            markDirty();
        });
        document.getElementById('scroll-fps').addEventListener('input', function() {
            document.getElementById('scroll-fps-value').textContent = this.value;
            markDirty();
        });

        // LED sign option selects just mark the screen dirty; values are read on save
        ['led-color', 'led-mode', 'led-speed', 'led-font'].forEach(id => {
            document.getElementById(id)?.addEventListener('change', markDirty);
        });

        document.getElementById('led-message-type')?.addEventListener('change', function() {
            const wantsGraphics = this.value === 'graphics';
            if (wantsGraphics === state.ledGraphicsMode) return;
            if (state.elements.length && !confirm(
                'Switching message type clears the current elements (text-mode lines and ' +
                'graphics-mode elements aren\'t interchangeable). Continue?'
            )) {
                this.value = state.ledGraphicsMode ? 'graphics' : 'text';
                return;
            }
            state.ledGraphicsMode = wantsGraphics;
            state.elements = [];
            state.selectedElement = null;
            hideElementProps();
            updateCanvasDimensions();
            updateDisplayPanels();
            rebuildPalette();
            updateLayers();
            render();
            commit();
        });

        // Canvas mouse events
        const canvasContainer = document.getElementById('canvas-container');
        canvasContainer.addEventListener('mousedown', handleCanvasMouseDown);
        canvasContainer.addEventListener('mousemove', handleCanvasMouseMove);
        canvasContainer.addEventListener('mouseup', handleCanvasMouseUp);
        canvasContainer.addEventListener('mouseleave', handleCanvasMouseUp);
        canvas.addEventListener('mousemove', updateMousePosition);

        // Data source modal
        const dataSourceModal = document.getElementById('dataSourceModal');
        const addDataSourceBtn = document.getElementById('btn-add-data-source');
        if (dataSourceModal && addDataSourceBtn) {
            addDataSourceBtn.addEventListener('click', () => new bootstrap.Modal(dataSourceModal).show());
        }
        const endpointSelect = document.getElementById('data-source-endpoint');
        if (endpointSelect) {
            endpointSelect.addEventListener('change', function() {
                const varInput = document.getElementById('data-source-var-name');
                const suggestion = ENDPOINT_VAR_SUGGESTIONS[this.value];
                if (varInput && suggestion && !varInput.value) varInput.value = suggestion;
            });
        }
        const testDataSourceBtn = document.getElementById('btn-test-data-source');
        if (testDataSourceBtn) testDataSourceBtn.addEventListener('click', testDataSource);
        const addDataSourceConfirmBtn = document.getElementById('btn-add-data-source-confirm');
        if (addDataSourceConfirmBtn) addDataSourceConfirmBtn.addEventListener('click', confirmAddDataSource);

        document.getElementById('btn-preview').addEventListener('click', showPreview);
        document.getElementById('btn-save').addEventListener('click', saveScreen);
        document.getElementById('btn-send-to-display')?.addEventListener('click', sendToDisplay);
        document.addEventListener('keydown', handleKeyDown);

        // Settings fields mark the screen dirty
        ['screen-name', 'screen-description', 'screen-duration'].forEach(id => {
            document.getElementById(id)?.addEventListener('input', markDirty);
        });
        document.getElementById('screen-enabled')?.addEventListener('change', markDirty);

        // Warn before navigating away with unsaved changes
        window.addEventListener('beforeunload', e => {
            if (state.dirty) {
                e.preventDefault();
                e.returnValue = '';
            }
        });

        bindVariableItems(document);
    }

    function bindVariableItems(root) {
        root.querySelectorAll('.variable-item').forEach(item => {
            if (item.dataset.bound) return;
            item.dataset.bound = '1';
            item.addEventListener('click', function() {
                const variable = this.dataset.var;
                const target = state.activeDynamicInput;
                if (target && variable) {
                    target.value += variable;
                    target.dispatchEvent(new Event('input', { bubbles: true }));
                    target.focus();
                }
            });
        });
    }

    // ------------------------------------------------------------------
    // Element palette (filtered by display type)
    // ------------------------------------------------------------------
    function rebuildPalette() {
        const palette = document.getElementById('element-palette');
        if (!palette) return;
        const key = paletteKey();
        const available = Object.keys(TYPES).filter(k => TYPES[k].displays.includes(key));
        palette.innerHTML = available.map(k => `
            <button type="button" class="palette-btn" data-type="${k}" title="Add ${TYPES[k].label}">
                <i class="fas ${TYPES[k].icon}"></i><span>${TYPES[k].label}</span>
            </button>`).join('');
    }

    function updateCanvasDimensions() {
        const dims = currentDisplayDims();
        state.canvasWidth = dims.width;
        state.canvasHeight = dims.height;
        canvas.width = dims.width;
        canvas.height = dims.height;
        document.getElementById('canvas-dimensions').textContent = `${dims.width} x ${dims.height} pixels`;

        const container = document.getElementById('canvas-container');
        container.classList.remove('display-oled', 'display-vfd', 'display-led');
        container.classList.add(`display-${state.displayType}`);

        applyZoom();
    }

    // Show the right option panels for the current display type
    function updateDisplayPanels() {
        const isLed = state.displayType === 'led';
        document.getElementById('effects-panel').style.display = isLed ? 'none' : 'block';
        const ledPanel = document.getElementById('led-options-panel');
        if (ledPanel) ledPanel.style.display = isLed ? 'block' : 'none';

        const ledTextOptions = document.getElementById('led-text-options');
        const ledGraphicsHelp = document.getElementById('led-graphics-help');
        if (ledTextOptions) ledTextOptions.style.display = state.ledGraphicsMode ? 'none' : 'block';
        if (ledGraphicsHelp) ledGraphicsHelp.style.display = state.ledGraphicsMode ? 'block' : 'none';
        const messageTypeSelect = document.getElementById('led-message-type');
        if (messageTypeSelect) messageTypeSelect.value = state.ledGraphicsMode ? 'graphics' : 'text';
    }

    // ------------------------------------------------------------------
    // Zoom & grid. The canvas keeps its logical (device) resolution and is
    // scaled up with CSS so pixels stay crisp; overlays are positioned in
    // screen coordinates (device px * zoom).
    // ------------------------------------------------------------------
    function applyZoom() {
        canvas.style.width = `${state.canvasWidth * state.zoom}px`;
        canvas.style.height = `${state.canvasHeight * state.zoom}px`;
        document.getElementById('zoom-level').textContent = `${state.zoom}×`;
        updateGridOverlay();
        updateOverlays();
    }

    function changeZoom(delta) {
        state.zoom = clamp(state.zoom + delta, 1, 10);
        applyZoom();
    }

    function updateGridOverlay() {
        const grid = document.getElementById('canvas-grid');
        if (!grid) return;
        grid.style.display = state.showGrid ? 'block' : 'none';
        if (!state.showGrid) return;
        const minor = 4 * state.zoom;
        const major = 8 * state.zoom;
        grid.style.backgroundImage = [
            'linear-gradient(to right, rgba(120,170,255,0.14) 1px, transparent 1px)',
            'linear-gradient(to bottom, rgba(120,170,255,0.14) 1px, transparent 1px)',
            'linear-gradient(to right, rgba(120,170,255,0.28) 1px, transparent 1px)',
            'linear-gradient(to bottom, rgba(120,170,255,0.28) 1px, transparent 1px)'
        ].join(',');
        grid.style.backgroundSize =
            `${minor}px ${minor}px, ${minor}px ${minor}px, ${major}px ${major}px, ${major}px ${major}px`;
    }

    // ------------------------------------------------------------------
    // Element CRUD
    // ------------------------------------------------------------------
    function addElement(type) {
        const def = TYPES[type];
        if (!def) return;
        const element = { id: Date.now(), ...def.create() };
        state.elements.push(element);
        selectElement(element.id);
        updateLayers();
        render();
        commit();
    }

    function selectElement(elementId) {
        state.selectedElement = elementId;
        const element = getElementById(elementId);
        if (element) {
            showElementProps(element);
            updateLayers();
            render();
        }
    }

    function deselectElement() {
        if (!state.selectedElement) return;
        state.selectedElement = null;
        hideElementProps();
        updateLayers();
        render();
    }

    function showElementProps(element) {
        const def = typeDef(element);
        const panel = document.getElementById('element-props-panel');
        panel.style.display = 'block';
        document.getElementById('element-props-icon').className = `fas ${def.icon}`;
        document.getElementById('element-props-title').textContent = `${def.label} Properties`;
        document.getElementById('element-props-fields').innerHTML = buildFieldsHtml(def, element);
        bindVariableItems(document);
    }

    function hideElementProps() {
        document.getElementById('element-props-panel').style.display = 'none';
    }

    function buildFieldsHtml(def, element) {
        let html = '<div class="fields-grid">';
        def.fields.forEach(f => {
            const val = element[f.key];
            const colClass = f.col === 6 ? 'fg-6' : 'fg-12';
            html += `<div class="form-group ${colClass}">`;
            if (f.kind === 'checkbox') {
                html += `<label><input type="checkbox" data-key="${f.key}" data-kind="checkbox" ${val ? 'checked' : ''}> ${f.label}</label>`;
            } else if (f.kind === 'select') {
                const options = f.key === 'font' ? fontOptionsForDisplay() : f.options;
                html += `<label>${f.label}</label><select class="form-control" data-key="${f.key}" data-kind="select">`;
                options.forEach(([v, lbl]) => {
                    html += `<option value="${v}" ${String(val || '') === String(v) ? 'selected' : ''}>${escapeHtml(lbl)}</option>`;
                });
                html += `</select>`;
            } else if (f.kind === 'range') {
                const v = val != null ? val : 0;
                html += `<label>${f.label}: <span class="range-live" data-for="${f.key}">${v}</span>${f.unit || ''}</label>`;
                html += `<input type="range" class="form-range" data-key="${f.key}" data-kind="range" min="${f.min}" max="${f.max}" value="${v}">`;
            } else if (f.kind === 'text') {
                const dyn = f.dynamic ? 'data-dynamic="1"' : '';
                html += `<label>${f.label}</label><input type="text" class="form-control" data-key="${f.key}" data-kind="text" ${dyn} value="${escapeHtml(val != null ? String(val) : '')}" placeholder="${escapeHtml(f.placeholder || '')}">`;
            } else { // number
                const v = val != null ? val : '';
                const min = f.min != null ? `min="${f.min}"` : '';
                html += `<label>${f.label}</label><input type="number" class="form-control" data-key="${f.key}" data-kind="number" ${min} value="${v}" placeholder="${escapeHtml(f.placeholder || '')}" ${f.allowNull ? 'data-nullable="1"' : ''}>`;
            }
            if (f.help) html += `<small class="form-text text-muted">${escapeHtml(f.help)}</small>`;
            html += `</div>`;
        });
        html += '</div>';
        return html;
    }

    function onFieldChange(e) {
        const input = e.target.closest('[data-key]');
        if (!input) return;
        if (input.dataset.dynamic) state.activeDynamicInput = input;

        const element = getElementById(state.selectedElement);
        if (!element) return;

        const key = input.dataset.key;
        const kind = input.dataset.kind;
        if (kind === 'checkbox') {
            element[key] = input.checked;
        } else if (kind === 'number' || kind === 'range') {
            if (input.dataset.nullable && input.value === '') {
                element[key] = null;
            } else {
                const n = parseInt(input.value, 10);
                element[key] = isNaN(n) ? (input.dataset.nullable ? null : 0) : n;
            }
            if (kind === 'range') {
                const live = document.querySelector(`.range-live[data-for="${key}"]`);
                if (live) live.textContent = element[key];
            }
        } else {
            element[key] = input.value;
        }

        updateLayers();
        render();
    }

    // Re-populate field inputs from the element (used after drag/resize/nudge).
    function syncFormFromElement(element) {
        if (!element || state.selectedElement !== element.id) return;
        const container = document.getElementById('element-props-fields');
        container.querySelectorAll('[data-key]').forEach(input => {
            const key = input.dataset.key;
            if (!(key in element)) return;
            if (input.dataset.kind === 'checkbox') input.checked = !!element[key];
            else input.value = element[key] != null ? element[key] : '';
            if (input.dataset.kind === 'range') {
                const live = document.querySelector(`.range-live[data-for="${key}"]`);
                if (live) live.textContent = element[key];
            }
        });
    }

    function deleteSelectedElement() {
        if (!state.selectedElement) return;
        state.elements = state.elements.filter(e => e.id !== state.selectedElement);
        state.selectedElement = null;
        hideElementProps();
        updateLayers();
        render();
        commit();
    }

    function duplicateSelectedElement() {
        if (!state.selectedElement) return;
        const element = getElementById(state.selectedElement);
        if (!element) return;
        const copy = { ...element, id: Date.now() };
        // Nudge so the copy is visible
        if ('x' in copy) copy.x += 6;
        if ('y' in copy) copy.y += 6;
        if ('x1' in copy) { copy.x1 += 6; copy.y1 += 6; copy.x2 += 6; copy.y2 += 6; }
        state.elements.push(copy);
        selectElement(copy.id);
        updateLayers();
        render();
        commit();
    }

    function getElementById(id) {
        return state.elements.find(e => e.id === id);
    }

    // ------------------------------------------------------------------
    // Layers
    // ------------------------------------------------------------------
    function updateLayers() {
        const layersList = document.getElementById('layers-list');
        document.getElementById('layer-count').textContent = state.elements.length;

        if (state.elements.length === 0) {
            layersList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-inbox"></i>
                    <p>No elements yet</p>
                    <small>Pick an element from the toolbar above the canvas</small>
                </div>`;
            return;
        }

        layersList.innerHTML = state.elements.map((element, index) => {
            const def = typeDef(element);
            const label = escapeHtml(def.layerLabel(element));
            const meta = 'x' in element ? `(${element.x}, ${element.y})` : '';
            return `
            <div class="layer-item ${state.selectedElement === element.id ? 'selected' : ''}"
                 data-element-id="${element.id}">
                <div class="layer-icon"><i class="fas ${def.icon}"></i></div>
                <div class="layer-content">
                    <div class="layer-text">${label}</div>
                    <div class="layer-meta">${def.label}${meta ? ' • ' + meta : ''}</div>
                </div>
                <div class="layer-actions">
                    <button class="layer-action-btn layer-move-up" ${index === 0 ? 'disabled' : ''}>
                        <i class="fas fa-arrow-up"></i>
                    </button>
                    <button class="layer-action-btn layer-move-down" ${index === state.elements.length - 1 ? 'disabled' : ''}>
                        <i class="fas fa-arrow-down"></i>
                    </button>
                </div>
            </div>`;
        }).join('');

        layersList.querySelectorAll('.layer-item').forEach(item => {
            const elementId = parseInt(item.dataset.elementId);
            item.addEventListener('click', (e) => {
                if (!e.target.closest('.layer-action-btn')) selectElement(elementId);
            });
            item.querySelector('.layer-move-up')?.addEventListener('click', (e) => {
                e.stopPropagation(); moveLayer(elementId, -1);
            });
            item.querySelector('.layer-move-down')?.addEventListener('click', (e) => {
                e.stopPropagation(); moveLayer(elementId, 1);
            });
        });
    }

    function moveLayer(elementId, direction) {
        const index = state.elements.findIndex(e => e.id === elementId);
        if (index === -1) return;
        const newIndex = index + direction;
        if (newIndex < 0 || newIndex >= state.elements.length) return;
        [state.elements[index], state.elements[newIndex]] = [state.elements[newIndex], state.elements[index]];
        updateLayers();
        render();
        commit();
    }

    // ------------------------------------------------------------------
    // Canvas rendering
    // ------------------------------------------------------------------
    function render() {
        ctx.fillStyle = theme().bg;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        state.elements.forEach(element => {
            try { typeDef(element).draw(element); } catch (err) { /* ignore bad element */ }
        });
        updateOverlays();
    }

    function updateOverlays() {
        const overlaysContainer = document.getElementById('element-overlays');
        if (!overlaysContainer) return;
        overlaysContainer.innerHTML = '';
        const z = state.zoom;
        state.elements.forEach(element => {
            const def = typeDef(element);
            const b = def.bounds(element);
            const overlay = document.createElement('div');
            overlay.className = 'element-overlay';
            const selected = state.selectedElement === element.id;
            if (selected) overlay.classList.add('selected');
            overlay.style.left = `${b.x * z}px`;
            overlay.style.top = `${b.y * z}px`;
            overlay.style.width = `${Math.max(6, b.w * z)}px`;
            overlay.style.height = `${Math.max(6, b.h * z)}px`;
            overlay.dataset.elementId = element.id;

            const label = document.createElement('div');
            label.className = 'element-overlay-label';
            label.textContent = def.layerLabel(element).substring(0, 22);
            overlay.appendChild(label);

            // Corner resize handle for resizable elements
            if (selected && def.resize) {
                const handle = document.createElement('div');
                handle.className = 'resize-handle';
                handle.title = 'Drag to resize';
                overlay.appendChild(handle);
            }

            overlaysContainer.appendChild(overlay);
        });
    }

    // ------------------------------------------------------------------
    // Canvas drag & resize
    // ------------------------------------------------------------------
    function canvasCoords(e) {
        const rect = canvas.getBoundingClientRect();
        return {
            x: Math.floor((e.clientX - rect.left) / state.zoom),
            y: Math.floor((e.clientY - rect.top) / state.zoom)
        };
    }

    // Keys that participate in generic move (snapshotted on drag start)
    const MOVE_KEYS = ['x', 'y', 'x1', 'y1', 'x2', 'y2', 'width', 'height', 'radius', 'size'];

    function captureStartProps(element) {
        const props = {};
        MOVE_KEYS.forEach(k => { if (k in element) props[k] = element[k]; });
        return props;
    }

    function handleCanvasMouseDown(e) {
        const pos = canvasCoords(e);
        const handle = e.target.closest('.resize-handle');
        const overlay = e.target.closest('.element-overlay');

        if (handle && overlay) {
            const elementId = parseInt(overlay.dataset.elementId);
            const element = getElementById(elementId);
            if (!element) return;
            selectElement(elementId);
            state.isResizing = true;
            state.dragElement = elementId;
            state.dragStartX = pos.x;
            state.dragStartY = pos.y;
            state.dragStartProps = captureStartProps(element);
            state.dragMoved = false;
            e.preventDefault();
            return;
        }

        if (overlay) {
            const elementId = parseInt(overlay.dataset.elementId);
            const element = getElementById(elementId);
            if (!element) return;
            selectElement(elementId);
            state.isDragging = true;
            state.dragElement = elementId;
            state.dragStartX = pos.x;
            state.dragStartY = pos.y;
            state.dragStartProps = captureStartProps(element);
            state.dragMoved = false;
            e.preventDefault();
            return;
        }

        // Click on empty canvas: deselect
        if (e.target === canvas) deselectElement();
    }

    function handleCanvasMouseMove(e) {
        if ((!state.isDragging && !state.isResizing) || !state.dragElement) return;
        const pos = canvasCoords(e);
        const element = getElementById(state.dragElement);
        if (!element || !state.dragStartProps) return;

        const tdx = pos.x - state.dragStartX;
        const tdy = pos.y - state.dragStartY;
        if (tdx === 0 && tdy === 0) return;
        state.dragMoved = true;

        const def = typeDef(element);
        const start = state.dragStartProps;

        if (state.isResizing && def.resize) {
            def.resize(element, start, tdx, tdy, snapValue);
        } else {
            // Generic move: translate every positional key from its start value
            if ('x' in start) element.x = clamp(snapValue(start.x + tdx), 0, state.canvasWidth);
            if ('y' in start) element.y = clamp(snapValue(start.y + tdy), 0, state.canvasHeight);
            if ('x1' in start) {
                element.x1 = snapValue(start.x1 + tdx);
                element.y1 = snapValue(start.y1 + tdy);
                element.x2 = snapValue(start.x2 + tdx);
                element.y2 = snapValue(start.y2 + tdy);
            }
        }

        syncFormFromElement(element);
        updateLayers();
        render();
    }

    function handleCanvasMouseUp() {
        const moved = state.dragMoved;
        state.isDragging = false;
        state.isResizing = false;
        state.dragElement = null;
        state.dragStartProps = null;
        state.dragMoved = false;
        if (moved) commit();
    }

    function updateMousePosition(e) {
        const pos = canvasCoords(e);
        document.getElementById('mouse-position').textContent = `X: ${pos.x}, Y: ${pos.y}`;
    }

    function nudgeSelected(dx, dy) {
        const element = getElementById(state.selectedElement);
        if (!element) return;
        if ('x1' in element) {
            element.x1 += dx; element.y1 += dy;
            element.x2 += dx; element.y2 += dy;
        } else if ('x' in element) {
            element.x = clamp(element.x + dx, 0, state.canvasWidth);
            element.y = clamp(element.y + dy, 0, state.canvasHeight);
        } else {
            return;
        }
        syncFormFromElement(element);
        updateLayers();
        render();
        // Coalesce rapid keypresses into one undo step
        clearTimeout(nudgeCommitTimer);
        nudgeCommitTimer = setTimeout(commit, 400);
    }

    function handleKeyDown(e) {
        const inField = ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName);

        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
            saveScreen();
            e.preventDefault();
            return;
        }
        if ((e.ctrlKey || e.metaKey) && !inField && e.key.toLowerCase() === 'z') {
            e.shiftKey ? redo() : undo();
            e.preventDefault();
            return;
        }
        if ((e.ctrlKey || e.metaKey) && !inField && e.key.toLowerCase() === 'y') {
            redo();
            e.preventDefault();
            return;
        }
        if ((e.key === 'Delete' || e.key === 'Backspace') && state.selectedElement && !inField) {
            deleteSelectedElement();
            e.preventDefault();
            return;
        }
        if ((e.ctrlKey || e.metaKey) && e.key === 'd' && state.selectedElement) {
            duplicateSelectedElement();
            e.preventDefault();
            return;
        }
        if (e.key === 'Escape' && state.selectedElement) {
            deselectElement();
            return;
        }
        if (!inField && state.selectedElement &&
            ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
            const step = e.shiftKey ? 8 : 1;
            const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0;
            const dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0;
            nudgeSelected(dx, dy);
            e.preventDefault();
        }
    }

    // ------------------------------------------------------------------
    // Data sources
    // ------------------------------------------------------------------
    function testDataSource() {
        const endpoint = document.getElementById('data-source-endpoint').value;
        if (!endpoint) { toast('Please select an endpoint', 'error'); return; }
        const preview = document.getElementById('data-source-preview');
        preview.innerHTML = '<div class="text-center"><i class="fas fa-spinner fa-spin"></i> Loading...</div>';
        preview.style.display = 'block';
        fetch(endpoint)
            .then(r => r.json())
            .then(data => { preview.innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`; })
            .catch(err => { preview.innerHTML = `<div class="text-danger">Error: ${escapeHtml(err.message)}</div>`; });
    }

    function confirmAddDataSource() {
        const endpoint = document.getElementById('data-source-endpoint').value;
        const varName = document.getElementById('data-source-var-name').value;
        if (!endpoint || !varName) { toast('Please fill in all fields', 'error'); return; }
        state.dataSources.push({ endpoint, var_name: varName });
        updateDataSourcesList();
        commit();
        bootstrap.Modal.getInstance(document.getElementById('dataSourceModal')).hide();
        document.getElementById('data-source-endpoint').value = '';
        document.getElementById('data-source-var-name').value = '';
        document.getElementById('data-source-preview').style.display = 'none';
    }

    function updateDataSourcesList() {
        const list = document.getElementById('data-sources-list');
        if (state.dataSources.length === 0) { list.innerHTML = ''; updateDynamicVariables(); return; }
        list.innerHTML = state.dataSources.map((source, index) => `
            <div class="data-source-item">
                <strong>${escapeHtml(source.var_name)}</strong>
                <code>${escapeHtml(source.endpoint)}</code>
                <button class="btn btn-sm btn-danger" onclick="ScreenEditor.removeDataSource(${index})">
                    <i class="fas fa-trash"></i>
                </button>
            </div>`).join('');
        updateDynamicVariables();
    }

    function removeDataSource(index) {
        state.dataSources.splice(index, 1);
        updateDataSourcesList();
        commit();
    }

    function updateDynamicVariables() {
        const container = document.getElementById('dynamic-variables');
        if (state.dataSources.length === 0) { container.innerHTML = ''; return; }
        container.innerHTML = '<strong>From Data Sources:</strong>';
        state.dataSources.forEach(source => {
            const div = document.createElement('div');
            div.className = 'variable-item';
            div.dataset.var = `{${source.var_name}.}`;
            div.innerHTML = `<code>{${escapeHtml(source.var_name)}.*}</code>
                <small>Access properties from ${escapeHtml(source.endpoint)}</small>`;
            container.appendChild(div);
        });
        bindVariableItems(container);
    }

    // ------------------------------------------------------------------
    // Preview
    // ------------------------------------------------------------------
    // Fallback: copy the editor's own client-side approximation onto the
    // preview canvas. Only used when the real server-side render (below)
    // is unavailable, so a preview is still better than none.
    function drawApproximatePreview() {
        const previewCanvas = document.getElementById('preview-canvas');
        const previewCtx = previewCanvas.getContext('2d');
        previewCanvas.width = canvas.width;
        previewCanvas.height = canvas.height;
        previewCtx.imageSmoothingEnabled = false;
        previewCtx.drawImage(canvas, 0, 0);
        previewCanvas.style.width = `${canvas.width * 4}px`;
        previewCanvas.style.height = `${canvas.height * 4}px`;
    }

    function showPreview() {
        const previewModal = document.getElementById('previewModal');
        if (previewModal) new bootstrap.Modal(previewModal).show();

        // Show the approximation immediately so the modal never looks
        // empty while the real render is in flight.
        drawApproximatePreview();

        fetch('/api/screens/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': window.CSRF_TOKEN },
            body: JSON.stringify({
                display_type: state.displayType,
                template_data: buildTemplateData(),
                data_sources: state.dataSources
            })
        })
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
            if (!ok || !data.image) {
                if (!ok) toast('Live preview unavailable — showing editor approximation', 'error');
                return;
            }
            // Pixel-accurate render from the same Pillow pipeline that
            // drives the real hardware (app_core.oled / scripts.vfd_
            // controller / scripts.led_sign_controller) -- replaces the
            // client-side approximation drawn above.
            const img = new Image();
            img.onload = () => {
                const previewCanvas = document.getElementById('preview-canvas');
                const previewCtx = previewCanvas.getContext('2d');
                previewCanvas.width = img.width;
                previewCanvas.height = img.height;
                previewCtx.drawImage(img, 0, 0);
                previewCanvas.style.width = `${canvas.width * 4}px`;
                previewCanvas.style.height = `${canvas.height * 4}px`;
            };
            img.src = data.image;
        })
        .catch(() => toast('Live preview unavailable — showing editor approximation', 'error'));
    }

    function sendToDisplay() {
        if (!state.screenId) {
            toast('Save the screen first, then send it to the display', 'error');
            return;
        }
        if (state.dirty) {
            toast('You have unsaved changes — save before sending', 'error');
            return;
        }
        fetch(`/api/screens/${state.screenId}/display`, {
            method: 'POST',
            headers: { 'X-CSRF-Token': window.CSRF_TOKEN }
        })
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
            if (ok) toast('Screen sent to display');
            else toast(data.error || 'Failed to send to display', 'error');
        })
        .catch(err => toast('Failed to send: ' + err.message, 'error'));
    }

    // ------------------------------------------------------------------
    // Save / load
    // ------------------------------------------------------------------
    function saveScreen() {
        const screenData = {
            name: document.getElementById('screen-name').value,
            description: document.getElementById('screen-description').value,
            display_type: state.displayType,
            enabled: document.getElementById('screen-enabled').checked,
            duration: parseInt(document.getElementById('screen-duration').value) || 10,
            template_data: buildTemplateData(),
            data_sources: state.dataSources
        };
        if (!screenData.name) { toast('Please enter a screen name', 'error'); return; }

        const url = state.screenId ? `/api/screens/${state.screenId}` : '/api/screens';
        const method = state.screenId ? 'PUT' : 'POST';
        fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': window.CSRF_TOKEN },
            body: JSON.stringify(screenData)
        })
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
            if (!ok || data.error) {
                toast('Error saving screen: ' + (data.error || 'unknown error'), 'error');
                return;
            }
            state.dirty = false;
            const created = !state.screenId;
            if (created && data.id) {
                // Stay in the editor and switch to edit mode for the new screen
                state.screenId = data.id;
                window.history.replaceState({}, '', `/screens/editor/${data.id}`);
            }
            document.getElementById('screen-name-display').textContent = screenData.name;
            toast(created ? 'Screen created' : 'Screen saved');
        })
        .catch(err => toast('Error saving screen: ' + err.message, 'error'));
    }

    function buildTemplateData() {
        if (state.displayType === 'led') {
            const color = document.getElementById('led-color')?.value || 'AMBER';

            if (state.ledGraphicsMode) {
                // Single-frame Dots/graphics mode -- render_led_elements()'s
                // {elements, color} contract (ScreenEditor._render_led_elements()
                // in scripts/screen_renderer.py). No mode/speed/font: those
                // are scrolling-text-only concepts.
                return {
                    elements: state.elements.map(e => typeDef(e).toTemplate(e)),
                    color
                };
            }

            // Legacy: character-based, emit a `lines` array consumed by
            // render_led_screen(), plus screen-level sign options.
            const lines = state.elements
                .filter(e => e.type === 'text')
                .map(e => ({ text: e.text }));
            return {
                lines,
                clear: true,
                color,
                mode: document.getElementById('led-mode')?.value || 'HOLD',
                speed: document.getElementById('led-speed')?.value || 'SPEED_3',
                font: document.getElementById('led-font')?.value || 'FONT_7x9'
            };
        }

        const elements = state.elements.map(e => typeDef(e).toTemplate(e));
        const template = { elements, clear: true };

        const scrollEffect = document.getElementById('scroll-effect').value;
        if (scrollEffect && scrollEffect !== 'static') {
            template.scroll_effect = scrollEffect;
            template.scroll_speed = parseInt(document.getElementById('scroll-speed').value);
            template.scroll_fps = parseInt(document.getElementById('scroll-fps').value);
        }
        return template;
    }

    function elementFromTemplate(t, index) {
        const def = TYPES[t.type] || (t.type === 'dotted_hline' ? TYPES.hline : null);
        if (def) {
            return { id: Date.now() + index, ...def.fromTemplate(t) };
        }
        // Unknown / advanced type (e.g. pixel_pattern): keep verbatim so it
        // round-trips on save even though it has no editor UI.
        return { id: Date.now() + index, type: t.type, _raw: t };
    }

    function loadScreen(screenData) {
        document.getElementById('screen-name').value = screenData.name || '';
        document.getElementById('screen-description').value = screenData.description || '';
        document.getElementById('display-type').value = screenData.display_type || 'oled';
        document.getElementById('screen-enabled').checked = screenData.enabled !== false;
        document.getElementById('screen-duration').value = screenData.duration || 10;

        state.displayType = screenData.display_type || 'oled';
        const td = screenData.template_data || {};
        state.ledGraphicsMode = state.displayType === 'led' && Array.isArray(td.elements);
        updateCanvasDimensions();
        updateDisplayPanels();
        rebuildPalette();

        if (Array.isArray(td.elements) && td.elements.length) {
            state.elements = td.elements.map(elementFromTemplate);
        } else if (Array.isArray(td.lines) && td.lines.length) {
            // Legacy lines format -> text elements, staggered vertically when
            // a line has no explicit y so they don't pile up at (0,0).
            const lineHeight = state.displayType === 'led' ? 8 : 13;
            state.elements = td.lines.map((line, index) => {
                const t = typeof line === 'string' ? { text: line } : line;
                const el = { id: Date.now() + index, ...TYPES.text.fromTemplate(t) };
                if (t.y == null) el.y = index * lineHeight;
                return el;
            });
        } else {
            state.elements = [];
        }

        // Scroll effects
        const scrollEffect = td.scroll_effect || 'static';
        document.getElementById('scroll-effect').value = scrollEffect;
        if (scrollEffect && scrollEffect !== 'static') {
            document.getElementById('scroll-speed').value = td.scroll_speed || 4;
            document.getElementById('scroll-fps').value = td.scroll_fps || 60;
            document.getElementById('scroll-speed-value').textContent = td.scroll_speed || 4;
            document.getElementById('scroll-fps-value').textContent = td.scroll_fps || 60;
            document.getElementById('scroll-speed-group').style.display = 'block';
            document.getElementById('scroll-fps-group').style.display = 'block';
        }

        // LED sign options
        if (state.displayType === 'led') {
            const setSel = (id, value) => {
                const sel = document.getElementById(id);
                if (sel && value) sel.value = value;
            };
            setSel('led-color', td.color);
            setSel('led-mode', td.mode);
            setSel('led-speed', td.speed);
            setSel('led-font', td.font);
        }

        if (screenData.data_sources) {
            state.dataSources = screenData.data_sources;
            updateDataSourcesList();
        }

        document.getElementById('screen-name-display').textContent = screenData.name || 'New Screen';
        updateLayers();
        render();
        resetHistory();
        state.dirty = false;
    }


    return { init, loadScreen, removeDataSource };
})();

document.addEventListener('DOMContentLoaded', () => {
    ScreenEditor.init();
});
