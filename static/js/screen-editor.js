/**
 * Visual Screen Editor for OLED/VFD/LED Displays
 *
 * Schema-driven WYSIWYG editor. Every element type is described once in the
 * TYPES registry (defaults, property fields, canvas drawing, overlay bounds,
 * and server (de)serialisation), so the toolbar, property panel, layer list,
 * canvas preview and save payload all stay in sync automatically.
 *
 * Supported graphics:
 *   text, bar, rectangle, line, hline, vline, circle, arc, icon, gauge, clock
 *
 * The available tools are filtered per display type:
 *   - oled: full graphics set (monochrome 128x64 SSD1306)
 *   - vfd:  text + shapes the GU-7000 hardware can draw (140x32)
 *   - led:  text only (character-based sign)
 */

const ScreenEditor = (function() {
    'use strict';

    // Editor state
    const state = {
        displayType: 'oled',
        canvasWidth: 128,
        canvasHeight: 64,
        zoom: 1,
        elements: [],
        selectedElement: null,
        dataSources: [],
        isDragging: false,
        dragElement: null,
        dragStartX: 0,
        dragStartY: 0,
        screenId: null,
        activeDynamicInput: null
    };

    // Display dimensions by type
    const DISPLAY_DIMS = {
        oled: { width: 128, height: 64 },
        vfd: { width: 140, height: 32 },
        led: { width: 80, height: 32 }  // Virtual dimensions for LED (4 lines x 20 chars)
    };

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

    // Built-in vector icons available on the OLED (mirrors app_core/oled.py)
    const ICON_NAMES = [
        'antenna', 'speaker', 'warning', 'check', 'cross',
        'network', 'shield', 'wave', 'clock', 'heartbeat'
    ];

    // Canvas and context
    let canvas, ctx;

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
        }
    };

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

    // ------------------------------------------------------------------
    // Element type registry
    //   create()        -> default props (id added by caller)
    //   fields          -> property panel schema
    //   draw(el)        -> render onto the canvas (white-on-black preview)
    //   bounds(el)      -> {x, y, w, h} top-left overlay box
    //   move(el,dx,dy)  -> reposition (defaults to x/y translate)
    //   toTemplate(el)  -> server JSON
    //   fromTemplate(t) -> editor props (id added by caller)
    //   layerLabel(el)  -> short label for the layers list
    //   displays        -> which display types may add this element
    // ------------------------------------------------------------------
    const TYPES = {
        text: {
            label: 'Text', icon: 'fa-font', displays: ['oled', 'vfd', 'led'],
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
                const w = Math.max(2, ctx.measureText(el.text || '').width);
                let x = el.x;
                if (el.align === 'right') x = el.x - w;
                else if (el.align === 'center') x = el.x - w / 2;
                if (el.invert) {
                    ctx.fillStyle = '#fff';
                    ctx.fillRect(x - 1, el.y - 1, w + 2, fontSize + 2);
                    ctx.fillStyle = '#000';
                } else {
                    ctx.fillStyle = '#fff';
                }
                ctx.fillText(el.text || '', x, el.y);
            },
            bounds(el) {
                const fontSize = FONT_SIZES[el.font] || 11;
                ctx.font = `${fontSize}px monospace`;
                const w = Math.max(10, ctx.measureText(el.text || '').width);
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
            label: 'Bar Graph', icon: 'fa-chart-bar', displays: ['oled', 'vfd'],
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
                ctx.strokeStyle = '#fff'; ctx.fillStyle = '#fff'; ctx.lineWidth = 1;
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
            toTemplate: el => ({ type: 'bar', x: el.x, y: el.y, width: el.width,
                height: el.height, value: el.value || '0', border: el.border !== false }),
            fromTemplate: t => ({ type: 'bar', x: t.x || 0, y: t.y || 0, width: t.width || 80,
                height: t.height || 9, value: t.value != null ? String(t.value) : '50',
                border: t.border !== false, preview: 60 }),
            layerLabel: el => `Bar ${el.width}×${el.height}`
        },

        rectangle: {
            label: 'Rectangle', icon: 'fa-square', displays: ['oled', 'vfd'],
            create: () => ({ type: 'rectangle', x: 4, y: 4, width: 30, height: 20, filled: false }),
            fields: [
                ...posFields(),
                { key: 'width', label: 'Width (px)', kind: 'number', col: 6, min: 1 },
                { key: 'height', label: 'Height (px)', kind: 'number', col: 6, min: 1 },
                { key: 'filled', label: 'Filled', kind: 'checkbox' }
            ],
            draw(el) {
                const w = Math.max(1, el.width), h = Math.max(1, el.height);
                ctx.strokeStyle = '#fff'; ctx.fillStyle = '#fff'; ctx.lineWidth = 1;
                if (el.filled) ctx.fillRect(el.x, el.y, w, h);
                else ctx.strokeRect(el.x + 0.5, el.y + 0.5, w - 1, h - 1);
            },
            bounds: el => ({ x: el.x, y: el.y, w: Math.max(1, el.width), h: Math.max(1, el.height) }),
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
                ctx.strokeStyle = '#fff';
                ctx.lineWidth = Math.max(1, el.lineWidth || 1);
                ctx.beginPath();
                ctx.moveTo(el.x1 + 0.5, el.y1 + 0.5);
                ctx.lineTo(el.x2 + 0.5, el.y2 + 0.5);
                ctx.stroke();
            },
            bounds: el => ({ x: Math.min(el.x1, el.x2), y: Math.min(el.y1, el.y2),
                w: Math.max(2, Math.abs(el.x2 - el.x1)), h: Math.max(2, Math.abs(el.y2 - el.y1)) }),
            move(el, dx, dy) { el.x1 += dx; el.y1 += dy; el.x2 += dx; el.y2 += dy; },
            toTemplate: el => ({ type: 'line', x1: el.x1, y1: el.y1, x2: el.x2, y2: el.y2,
                width: el.lineWidth || 1 }),
            fromTemplate: t => ({ type: 'line', x1: t.x1 || 0, y1: t.y1 || 0, x2: t.x2 || 0,
                y2: t.y2 || 0, lineWidth: t.width || 1 }),
            layerLabel: el => `Line (${el.x1},${el.y1})→(${el.x2},${el.y2})`
        },

        hline: {
            label: 'Horizontal Divider', icon: 'fa-grip-lines', displays: ['oled', 'vfd'],
            create: () => ({ type: 'hline', x: 0, y: 16, width: 64, dotted: false }),
            fields: [
                ...posFields(),
                { key: 'width', label: 'Width (px)', kind: 'number', min: 1 },
                { key: 'dotted', label: 'Dotted', kind: 'checkbox' }
            ],
            draw(el) {
                ctx.strokeStyle = '#fff'; ctx.fillStyle = '#fff'; ctx.lineWidth = 1;
                const w = Math.max(1, el.width);
                if (el.dotted) {
                    for (let px = 0; px < w; px += 2) ctx.fillRect(el.x + px, el.y, 1, 1);
                } else {
                    ctx.beginPath();
                    ctx.moveTo(el.x, el.y + 0.5); ctx.lineTo(el.x + w, el.y + 0.5); ctx.stroke();
                }
            },
            bounds: el => ({ x: el.x, y: el.y - 2, w: Math.max(1, el.width), h: 5 }),
            toTemplate: el => ({ type: el.dotted ? 'dotted_hline' : 'hline', x: el.x, y: el.y, width: el.width }),
            fromTemplate: t => ({ type: 'hline', x: t.x || 0, y: t.y || 0, width: t.width || 64,
                dotted: t.type === 'dotted_hline' }),
            layerLabel: el => `${el.dotted ? 'Dotted ' : ''}H-Line ${el.width}px`
        },

        vline: {
            label: 'Vertical Divider', icon: 'fa-grip-lines-vertical', displays: ['oled', 'vfd'],
            create: () => ({ type: 'vline', x: 16, y: 0, height: 32 }),
            fields: [
                ...posFields(),
                { key: 'height', label: 'Height (px)', kind: 'number', min: 1 }
            ],
            draw(el) {
                ctx.strokeStyle = '#fff'; ctx.lineWidth = 1;
                const h = Math.max(1, el.height);
                ctx.beginPath();
                ctx.moveTo(el.x + 0.5, el.y); ctx.lineTo(el.x + 0.5, el.y + h); ctx.stroke();
            },
            bounds: el => ({ x: el.x - 2, y: el.y, w: 5, h: Math.max(1, el.height) }),
            toTemplate: el => ({ type: 'vline', x: el.x, y: el.y, height: el.height }),
            fromTemplate: t => ({ type: 'vline', x: t.x || 0, y: t.y || 0, height: t.height || 32 }),
            layerLabel: el => `V-Line ${el.height}px`
        },

        circle: {
            label: 'Circle', icon: 'fa-circle', displays: ['oled'],
            create: () => ({ type: 'circle', x: 32, y: 32, radius: 12, filled: false }),
            fields: [
                { key: 'x', label: 'Center X', kind: 'number', col: 6 },
                { key: 'y', label: 'Center Y', kind: 'number', col: 6 },
                { key: 'radius', label: 'Radius (px)', kind: 'number', min: 1 },
                { key: 'filled', label: 'Filled', kind: 'checkbox' }
            ],
            draw(el) {
                ctx.strokeStyle = '#fff'; ctx.fillStyle = '#fff'; ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.arc(el.x, el.y, Math.max(1, el.radius), 0, 2 * Math.PI);
                if (el.filled) ctx.fill(); else ctx.stroke();
            },
            bounds: el => ({ x: el.x - el.radius, y: el.y - el.radius, w: el.radius * 2, h: el.radius * 2 }),
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
                ctx.strokeStyle = '#fff'; ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.arc(el.x, el.y, Math.max(1, el.radius),
                    (el.start || 0) * Math.PI / 180, (el.end || 0) * Math.PI / 180);
                ctx.stroke();
            },
            bounds: el => ({ x: el.x - el.radius, y: el.y - el.radius, w: el.radius * 2, h: el.radius * 2 }),
            toTemplate: el => ({ type: 'arc', x: el.x, y: el.y, radius: el.radius, start: el.start, end: el.end }),
            fromTemplate: t => ({ type: 'arc', x: t.x || 32, y: t.y || 32, radius: t.radius || 14,
                start: t.start || 0, end: t.end != null ? t.end : 180 }),
            layerLabel: el => `Arc ${el.start}–${el.end}°`
        },

        icon: {
            label: 'Icon', icon: 'fa-icons', displays: ['oled'],
            create: () => ({ type: 'icon', name: 'antenna', x: 4, y: 4, size: 16 }),
            fields: [
                { key: 'name', label: 'Icon', kind: 'select', options: ICON_NAMES.map(n => [n, n]) },
                ...posFields(),
                { key: 'size', label: 'Size (px)', kind: 'number', min: 6 }
            ],
            draw(el) {
                ctx.strokeStyle = '#fff'; ctx.fillStyle = '#fff'; ctx.lineWidth = 1;
                const fn = ICON_DRAW[el.name];
                if (fn) fn(ctx, el.x, el.y, Math.max(6, el.size));
                else ctx.strokeRect(el.x + 0.5, el.y + 0.5, el.size - 1, el.size - 1);
            },
            bounds: el => ({ x: el.x, y: el.y, w: Math.max(6, el.size), h: Math.max(6, el.size) }),
            toTemplate: el => ({ type: 'icon', name: el.name, x: el.x, y: el.y, size: el.size }),
            fromTemplate: t => ({ type: 'icon', name: t.name || 'antenna', x: t.x || 0, y: t.y || 0,
                size: t.size || 16 }),
            layerLabel: el => `Icon: ${el.name}`
        },

        gauge: {
            label: 'Gauge', icon: 'fa-gauge-high', displays: ['oled'],
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
                ctx.strokeStyle = '#fff'; ctx.fillStyle = '#fff'; ctx.lineWidth = 1;
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
            toTemplate: el => ({ type: 'gauge', x: el.x, y: el.y, radius: el.radius, value: el.value || '0' }),
            fromTemplate: t => ({ type: 'gauge', x: t.x || 64, y: t.y || 48, radius: t.radius || 24,
                value: t.value != null ? String(t.value) : '50', preview: 60 }),
            layerLabel: el => `Gauge r${el.radius}`
        },

        clock: {
            label: 'Analog Clock', icon: 'fa-clock', displays: ['oled'],
            create: () => ({ type: 'clock', x: 32, y: 32, radius: 28, showSeconds: false, showTicks: true }),
            fields: [
                { key: 'x', label: 'Center X', kind: 'number', col: 6 },
                { key: 'y', label: 'Center Y', kind: 'number', col: 6 },
                { key: 'radius', label: 'Radius (px)', kind: 'number', min: 8 },
                { key: 'showTicks', label: 'Hour Ticks', kind: 'checkbox' },
                { key: 'showSeconds', label: 'Second Hand', kind: 'checkbox' }
            ],
            draw(el) {
                ctx.strokeStyle = '#fff'; ctx.fillStyle = '#fff'; ctx.lineWidth = 1;
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

    function typeDef(el) { return TYPES[el.type] || TYPES.text; }

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

        setupEventListeners();
        updateCanvasDimensions();
        rebuildAddMenu();
        render();
    }

    function setupEventListeners() {
        document.getElementById('display-type').addEventListener('change', function() {
            state.displayType = this.value;
            updateCanvasDimensions();
            updateEffectsPanel();
            rebuildAddMenu();
            render();
        });

        // Add-element selector
        const addSelect = document.getElementById('add-element-select');
        if (addSelect) {
            addSelect.addEventListener('change', function() {
                if (this.value) {
                    addElement(this.value);
                    this.value = '';
                }
            });
        }

        document.getElementById('btn-clear-canvas').addEventListener('click', () => {
            if (confirm('Clear all elements?')) {
                state.elements = [];
                state.selectedElement = null;
                render();
                updateLayers();
                hideElementProps();
            }
        });

        document.getElementById('btn-zoom-in').addEventListener('click', () => changeZoom(0.25));
        document.getElementById('btn-zoom-out').addEventListener('click', () => changeZoom(-0.25));

        // Element actions (single shared panel)
        document.getElementById('btn-delete-element').addEventListener('click', deleteSelectedElement);
        document.getElementById('btn-duplicate-element').addEventListener('click', duplicateSelectedElement);

        // Delegated property field changes
        document.getElementById('element-props-fields').addEventListener('input', onFieldChange);
        document.getElementById('element-props-fields').addEventListener('change', onFieldChange);

        // Scroll effect controls
        document.getElementById('scroll-effect').addEventListener('change', function() {
            const needsSpeed = !['static', 'fade_in'].includes(this.value);
            document.getElementById('scroll-speed-group').style.display = needsSpeed ? 'block' : 'none';
            document.getElementById('scroll-fps-group').style.display = needsSpeed ? 'block' : 'none';
        });
        document.getElementById('scroll-speed').addEventListener('input', function() {
            document.getElementById('scroll-speed-value').textContent = this.value;
        });
        document.getElementById('scroll-fps').addEventListener('input', function() {
            document.getElementById('scroll-fps-value').textContent = this.value;
        });

        // Canvas mouse events
        const canvasContainer = document.getElementById('canvas-container');
        canvasContainer.addEventListener('mousedown', handleCanvasMouseDown);
        canvasContainer.addEventListener('mousemove', handleCanvasMouseMove);
        canvasContainer.addEventListener('mouseup', handleCanvasMouseUp);
        canvas.addEventListener('mousemove', updateMousePosition);

        // Data source modal
        const dataSourceModal = document.getElementById('dataSourceModal');
        const addDataSourceBtn = document.getElementById('btn-add-data-source');
        if (dataSourceModal && addDataSourceBtn) {
            addDataSourceBtn.addEventListener('click', () => new bootstrap.Modal(dataSourceModal).show());
        }
        const testDataSourceBtn = document.getElementById('btn-test-data-source');
        if (testDataSourceBtn) testDataSourceBtn.addEventListener('click', testDataSource);
        const addDataSourceConfirmBtn = document.getElementById('btn-add-data-source-confirm');
        if (addDataSourceConfirmBtn) addDataSourceConfirmBtn.addEventListener('click', confirmAddDataSource);

        document.getElementById('btn-preview').addEventListener('click', showPreview);
        document.getElementById('btn-save').addEventListener('click', saveScreen);
        document.addEventListener('keydown', handleKeyDown);

        // Built-in variable helper clicks
        document.querySelectorAll('#dynamic-variables, .variable-help').forEach(() => {});
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
    // Add-element menu (filtered by display type)
    // ------------------------------------------------------------------
    function rebuildAddMenu() {
        const select = document.getElementById('add-element-select');
        if (!select) return;
        const available = Object.keys(TYPES).filter(k => TYPES[k].displays.includes(state.displayType));
        select.innerHTML = '<option value="">+ Add Element…</option>' +
            available.map(k => `<option value="${k}">${TYPES[k].label}</option>`).join('');
    }

    function updateCanvasDimensions() {
        const dims = DISPLAY_DIMS[state.displayType];
        state.canvasWidth = dims.width;
        state.canvasHeight = dims.height;
        canvas.width = dims.width;
        canvas.height = dims.height;
        document.getElementById('canvas-dimensions').textContent = `${dims.width} x ${dims.height} pixels`;
    }

    function updateEffectsPanel() {
        document.getElementById('effects-panel').style.display =
            state.displayType === 'led' ? 'none' : 'block';
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
                html += `<label>${f.label}</label><select class="form-control" data-key="${f.key}" data-kind="select">`;
                f.options.forEach(([v, lbl]) => {
                    html += `<option value="${v}" ${String(val) === String(v) ? 'selected' : ''}>${escapeHtml(lbl)}</option>`;
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

    // Re-populate field inputs from the element (used after drag).
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
                    <small>Use "+ Add Element…" to start</small>
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
    }

    // ------------------------------------------------------------------
    // Canvas rendering
    // ------------------------------------------------------------------
    function render() {
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        state.elements.forEach(element => {
            try { typeDef(element).draw(element); } catch (err) { /* ignore bad element */ }
        });
        updateOverlays();
    }

    function updateOverlays() {
        const overlaysContainer = document.getElementById('element-overlays');
        overlaysContainer.innerHTML = '';
        state.elements.forEach(element => {
            const def = typeDef(element);
            const b = def.bounds(element);
            const overlay = document.createElement('div');
            overlay.className = 'element-overlay';
            if (state.selectedElement === element.id) overlay.classList.add('selected');
            overlay.style.left = `${b.x}px`;
            overlay.style.top = `${b.y}px`;
            overlay.style.width = `${Math.max(6, b.w)}px`;
            overlay.style.height = `${Math.max(6, b.h)}px`;
            overlay.dataset.elementId = element.id;

            const label = document.createElement('div');
            label.className = 'element-overlay-label';
            label.textContent = def.layerLabel(element).substring(0, 22);
            overlay.appendChild(label);
            overlaysContainer.appendChild(overlay);
        });
    }

    // ------------------------------------------------------------------
    // Canvas drag
    // ------------------------------------------------------------------
    function handleCanvasMouseDown(e) {
        const rect = canvas.getBoundingClientRect();
        const x = Math.floor((e.clientX - rect.left) / state.zoom);
        const y = Math.floor((e.clientY - rect.top) / state.zoom);
        const overlay = e.target.closest('.element-overlay');
        if (overlay) {
            const elementId = parseInt(overlay.dataset.elementId);
            selectElement(elementId);
            state.isDragging = true;
            state.dragElement = elementId;
            state.dragStartX = x;
            state.dragStartY = y;
            e.preventDefault();
        }
    }

    function handleCanvasMouseMove(e) {
        if (!state.isDragging || !state.dragElement) return;
        const rect = canvas.getBoundingClientRect();
        const x = Math.floor((e.clientX - rect.left) / state.zoom);
        const y = Math.floor((e.clientY - rect.top) / state.zoom);
        const element = getElementById(state.dragElement);
        if (!element) return;

        let dx = x - state.dragStartX;
        let dy = y - state.dragStartY;
        const def = typeDef(element);
        if (def.move) def.move(element, dx, dy);
        else {
            element.x = clamp(element.x + dx, 0, state.canvasWidth);
            element.y = clamp(element.y + dy, 0, state.canvasHeight);
        }

        state.dragStartX = x;
        state.dragStartY = y;
        syncFormFromElement(element);
        updateLayers();
        render();
    }

    function handleCanvasMouseUp() {
        state.isDragging = false;
        state.dragElement = null;
    }

    function updateMousePosition(e) {
        const rect = canvas.getBoundingClientRect();
        const x = Math.floor((e.clientX - rect.left) / state.zoom);
        const y = Math.floor((e.clientY - rect.top) / state.zoom);
        document.getElementById('mouse-position').textContent = `X: ${x}, Y: ${y}`;
    }

    function changeZoom(delta) {
        state.zoom = clamp(state.zoom + delta, 0.5, 4);
        document.getElementById('canvas-container').style.transform = `scale(${state.zoom})`;
        document.getElementById('zoom-level').textContent = `${Math.round(state.zoom * 100)}%`;
    }

    function handleKeyDown(e) {
        const inField = ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName);
        if ((e.key === 'Delete' || e.key === 'Backspace') && state.selectedElement && !inField) {
            deleteSelectedElement();
            e.preventDefault();
        }
        if ((e.ctrlKey || e.metaKey) && e.key === 'd' && state.selectedElement) {
            duplicateSelectedElement();
            e.preventDefault();
        }
        if (e.key === 'Escape' && state.selectedElement) {
            state.selectedElement = null;
            hideElementProps();
            updateLayers();
            render();
        }
    }

    // ------------------------------------------------------------------
    // Data sources
    // ------------------------------------------------------------------
    function testDataSource() {
        const endpoint = document.getElementById('data-source-endpoint').value;
        if (!endpoint) { alert('Please select an endpoint'); return; }
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
        if (!endpoint || !varName) { alert('Please fill in all fields'); return; }
        state.dataSources.push({ endpoint, var_name: varName });
        updateDataSourcesList();
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
    function showPreview() {
        const previewCanvas = document.getElementById('preview-canvas');
        const previewCtx = previewCanvas.getContext('2d');
        previewCanvas.width = canvas.width;
        previewCanvas.height = canvas.height;
        previewCtx.drawImage(canvas, 0, 0);
        const previewModal = document.getElementById('previewModal');
        if (previewModal) new bootstrap.Modal(previewModal).show();
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
        if (!screenData.name) { alert('Please enter a screen name'); return; }

        const url = state.screenId ? `/api/screens/${state.screenId}` : '/api/screens';
        const method = state.screenId ? 'PUT' : 'POST';
        fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': window.CSRF_TOKEN },
            body: JSON.stringify(screenData)
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) alert('Error saving screen: ' + data.error);
            else { alert('Screen saved successfully!'); window.location.href = '/screens'; }
        })
        .catch(err => alert('Error saving screen: ' + err.message));
    }

    function buildTemplateData() {
        // LED is character-based: emit a `lines` array consumed by render_led_screen.
        if (state.displayType === 'led') {
            const lines = state.elements
                .filter(e => e.type === 'text')
                .map(e => ({ text: e.text, font: e.font }));
            return { lines, clear: true };
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
        updateCanvasDimensions();
        updateEffectsPanel();
        rebuildAddMenu();

        const td = screenData.template_data || {};
        if (Array.isArray(td.elements) && td.elements.length) {
            state.elements = td.elements.map(elementFromTemplate);
        } else if (Array.isArray(td.lines) && td.lines.length) {
            // Legacy lines format -> text elements
            state.elements = td.lines.map((line, index) => {
                if (typeof line === 'string') {
                    return { id: Date.now() + index, ...TYPES.text.fromTemplate({ text: line }) };
                }
                return { id: Date.now() + index, ...TYPES.text.fromTemplate(line) };
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

        if (screenData.data_sources) {
            state.dataSources = screenData.data_sources;
            updateDataSourcesList();
        }

        document.getElementById('screen-name-display').textContent = screenData.name || 'New Screen';
        updateLayers();
        render();
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : text;
        return div.innerHTML;
    }

    return { init, loadScreen, removeDataSource };
})();

document.addEventListener('DOMContentLoaded', () => {
    ScreenEditor.init();
});
