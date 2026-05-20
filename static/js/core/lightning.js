/**
 * EAS Station ™ - Lightning Theme Bolt Renderer
 *
 * When the "lightning" theme is active, this module drives a storm overlay:
 *
 *   - A full-viewport flash layer that briefly illuminates the sky in sync
 *     with each strike (radial gradient from the strike origin, CSS blur
 *     via filter + mix-blend-mode: screen).
 *   - 1 to 3 procedurally generated SVG bolts per strike, spawned at random
 *     positions and angles; trunks + recursive branches, stroke width
 *     tapered to near-zero at the tips, rendered with real `filter: blur`
 *     so they actually glow into surrounding pixels.
 *   - JS-scheduled strikes at irregular intervals (3.5–11 s), with a ~35%
 *     chance of a double-strike flicker (classic lightning flutter).
 *   - Fast in (20 ms), slow afterglow out (~500 ms).
 *
 * The overlay is created/destroyed in response to the `theme-changed`
 * event dispatched by theme.js.
 */
(function() {
    'use strict';

    const LIGHTNING = 'lightning';
    const SVG_NS = 'http://www.w3.org/2000/svg';
    const VIEW_W = 1200;
    const VIEW_H = 800;

    let overlay = null;
    let flashEl = null;
    let boltsLayer = null;
    let nextStrikeTimer = null;
    let active = false;

    function rand(min, max) {
        return Math.random() * (max - min) + min;
    }
    function chance(p) {
        return Math.random() < p;
    }
    function pick(arr) {
        return arr[Math.floor(Math.random() * arr.length)];
    }

    /* Trunk: drifts down with jitter; segment step length varies so the
       rhythm is uneven (real bolts don't have even zigzag). */
    function generateTrunk(startX, startY, endY, segmentCount, drift) {
        const points = [{ x: startX, y: startY }];
        let y = startY;
        let x = startX;
        const avgStep = (endY - startY) / segmentCount;
        for (let i = 1; i < segmentCount; i++) {
            const step = avgStep * rand(0.55, 1.45);
            y = Math.min(endY, y + step);
            x += rand(-drift, drift);
            points.push({ x, y });
        }
        points.push({ x: x + rand(-drift, drift), y: endY });
        return points;
    }

    /* Branches fork outward from random trunk vertices and can recurse. */
    function generateBranches(parent, spawnChance, depth, baseWidth, sideHint) {
        const out = [];
        if (depth <= 0) return out;
        for (let i = 1; i < parent.length - 1; i++) {
            if (!chance(spawnChance)) continue;
            const origin = parent[i];
            const direction = sideHint !== undefined
                ? sideHint * (chance(0.75) ? 1 : -1)
                : (chance(0.5) ? -1 : 1);
            const length = rand(60, 200);
            const segments = Math.floor(rand(3, 8));
            const step = length / segments;
            const angle = rand(0.55, 1.25);
            const branch = [{ x: origin.x, y: origin.y }];
            let cx = origin.x;
            let cy = origin.y;
            for (let j = 1; j <= segments; j++) {
                const lateral = Math.sin(angle + rand(-0.35, 0.35)) * step * direction;
                const descent = Math.cos(angle) * step * 0.65 + rand(-step * 0.15, step * 0.35);
                cx += lateral;
                cy += descent;
                branch.push({ x: cx, y: cy });
            }
            out.push({ points: branch, width: baseWidth });
            if (depth > 1 && chance(spawnChance * 0.6)) {
                out.push(...generateBranches(
                    branch,
                    spawnChance * 0.5,
                    depth - 1,
                    baseWidth * 0.55,
                    direction
                ));
            }
        }
        return out;
    }

    function appendSegment(group, p1, p2, width, color, opacity) {
        if (width < 0.08) return;
        const seg = document.createElementNS(SVG_NS, 'path');
        seg.setAttribute('d', `M${p1.x.toFixed(1)} ${p1.y.toFixed(1)} L${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`);
        seg.setAttribute('stroke', color);
        seg.setAttribute('stroke-width', width.toFixed(2));
        seg.setAttribute('stroke-linecap', 'round');
        seg.setAttribute('fill', 'none');
        seg.setAttribute('opacity', opacity.toFixed(2));
        group.appendChild(seg);
    }

    /* Single bright white stroke per segment — the stacked drop-shadow
       filters in CSS add the volumetric glow. Drawing three concentric
       strokes (as before) was what made bolts look like line art. */
    function renderPolyline(group, points, baseWidth, taper) {
        const total = points.length - 1;
        if (total <= 0) return;
        for (let i = 0; i < total; i++) {
            const t = i / total;
            const width = Math.max(0.1, baseWidth * Math.pow(1 - t, taper));
            appendSegment(group, points[i], points[i + 1], width, '#ffffff', 1);
        }
    }

    function buildBolt(origin) {
        const svg = document.createElementNS(SVG_NS, 'svg');
        svg.setAttribute('viewBox', `0 0 ${VIEW_W} ${VIEW_H}`);
        svg.setAttribute('preserveAspectRatio', 'xMidYMid slice');
        svg.setAttribute('aria-hidden', 'true');
        svg.classList.add('lightning-bolt');

        const rootX = origin.x;
        const endY = rand(680, 860);
        const segments = Math.floor(rand(12, 20));
        const drift = rand(25, 55);
        const trunk = generateTrunk(rootX, -30, endY, segments, drift);

        const centerBias = rootX < VIEW_W / 2 ? 1 : -1;
        const branches = generateBranches(trunk, 0.38, 2, 1.5, centerBias);

        const group = document.createElementNS(SVG_NS, 'g');
        renderPolyline(group, trunk, 2.8, 1.3);
        branches.forEach(b => renderPolyline(group, b.points, b.width * 1.3, 1.5));
        svg.appendChild(group);

        return { svg, origin };
    }

    function triggerFlash(origin) {
        if (!flashEl) return;
        const fx = (origin.x / VIEW_W) * 100;
        const fy = Math.max(2, (origin.y / VIEW_H) * 100);
        flashEl.style.setProperty('--flash-x', fx.toFixed(1) + '%');
        flashEl.style.setProperty('--flash-y', fy.toFixed(1) + '%');
        flashEl.classList.remove('lightning-flash-on');
        /* Force reflow so the class re-trigger restarts the transition. */
        void flashEl.offsetWidth;
        flashEl.classList.add('lightning-flash-on');
        setTimeout(() => {
            if (flashEl) flashEl.classList.remove('lightning-flash-on');
        }, 80);
    }

    function strikeBolts(bolts) {
        bolts.forEach(({ svg }) => {
            boltsLayer.appendChild(svg);
            /* Force layout, then flip to the "strike" state so the transition
               actually animates rather than rendering at the end state. */
            void svg.offsetWidth;
            svg.classList.add('lightning-bolt-strike');
        });
    }

    function fadeBolts(bolts) {
        bolts.forEach(({ svg }) => svg.classList.add('lightning-bolt-fade'));
        setTimeout(() => {
            bolts.forEach(({ svg }) => svg.remove());
        }, 650);
    }

    function performStrike() {
        if (!overlay) return;
        const boltCount = chance(0.55) ? 1 : (chance(0.7) ? 2 : 3);
        const bolts = [];
        for (let i = 0; i < boltCount; i++) {
            const origin = {
                x: rand(VIEW_W * 0.08, VIEW_W * 0.92),
                y: rand(-20, 40)
            };
            bolts.push(buildBolt(origin));
        }
        const primary = bolts[0].origin;
        triggerFlash(primary);
        strikeBolts(bolts);

        /* Classic double-strike flicker: a real bolt often flashes twice. */
        if (chance(0.35)) {
            setTimeout(() => {
                bolts.forEach(({ svg }) => svg.classList.add('lightning-bolt-dim'));
                setTimeout(() => {
                    bolts.forEach(({ svg }) => svg.classList.remove('lightning-bolt-dim'));
                    triggerFlash(primary);
                }, rand(40, 80));
            }, rand(70, 130));
        }

        /* Afterglow: start fading after a short hold, fully remove later. */
        setTimeout(() => fadeBolts(bolts), 220);
    }

    function scheduleNextStrike() {
        if (!active) return;
        const wait = rand(3500, 11000);
        nextStrikeTimer = setTimeout(() => {
            performStrike();
            scheduleNextStrike();
        }, wait);
    }

    function mount() {
        if (overlay) return;
        overlay = document.createElement('div');
        overlay.id = 'lightning-overlay';
        overlay.setAttribute('aria-hidden', 'true');

        flashEl = document.createElement('div');
        flashEl.className = 'lightning-flash';
        overlay.appendChild(flashEl);

        boltsLayer = document.createElement('div');
        boltsLayer.className = 'lightning-bolts';
        overlay.appendChild(boltsLayer);

        document.body.appendChild(overlay);

        active = true;
        /* Fire an initial strike after a short breath so it doesn't feel
           like the page is broken — but delay it past the theme switch. */
        nextStrikeTimer = setTimeout(() => {
            performStrike();
            scheduleNextStrike();
        }, 900);
    }

    function unmount() {
        active = false;
        if (nextStrikeTimer) {
            clearTimeout(nextStrikeTimer);
            nextStrikeTimer = null;
        }
        if (overlay) {
            overlay.remove();
            overlay = null;
            flashEl = null;
            boltsLayer = null;
        }
    }

    function sync(theme) {
        if (theme === LIGHTNING) mount();
        else unmount();
    }

    /* Respect reduced-motion — no flashes or bolts at all. */
    const reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    window.addEventListener('theme-changed', (e) => {
        if (reducedMotion) return;
        sync(e.detail && e.detail.theme);
    });

    function init() {
        if (reducedMotion) return;
        sync(document.documentElement.getAttribute('data-theme'));
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
