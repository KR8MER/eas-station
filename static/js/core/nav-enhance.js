/**
 * EAS Station™ — Global navigation enhancements
 *
 *  1. Command palette (Ctrl/Cmd+K): fuzzy-search every page reachable from
 *     the navbar and jump straight to it, bypassing nested dropdowns.
 *  2. Breadcrumb trail: derives "Section › Group › Page" for the current
 *     URL from the navbar structure and renders it under the navbar.
 *
 * Both features index the *rendered* navbar DOM rather than a separate page
 * registry, so they automatically respect permission-based visibility
 * (links the current user can't see are never indexed) and stay correct
 * whenever the navbar changes.
 */
(function () {
    'use strict';

    // ---- Page index from the navbar DOM -----------------------------------

    function cleanText(el) {
        return (el ? el.textContent : '').replace(/\s+/g, ' ').trim();
    }

    function buildIndex() {
        const entries = [];
        const seen = new Set();
        const nav = document.querySelector('.navbar');
        if (!nav) return entries;

        function add(label, href, trail) {
            if (!label || !href || href === '#' || href.startsWith('javascript:')) return;
            const key = `${label}|${href}`;
            if (seen.has(key)) return;
            seen.add(key);
            entries.push({ label, href, trail: trail || [] });
        }

        nav.querySelectorAll('.navbar-nav > .nav-item').forEach((item) => {
            const toggle = item.querySelector(':scope > .nav-link');
            const section = cleanText(toggle);
            const menu = item.querySelector(':scope > .dropdown-menu');

            if (!menu) {
                if (toggle) add(section, toggle.getAttribute('href'), []);
                return;
            }

            let group = '';
            menu.querySelectorAll(':scope > li').forEach((li) => {
                const header = li.querySelector(':scope > .dropdown-header');
                if (header) {
                    group = cleanText(header);
                    return;
                }
                const link = li.querySelector(':scope > a.dropdown-item[href]');
                if (!link) return;
                const trail = [section];
                if (group) trail.push(group);
                add(cleanText(link), link.getAttribute('href'), trail);
            });
        });

        return entries;
    }

    // ---- Styles (injected so the feature stays self-contained) ------------

    function injectStyles() {
        const style = document.createElement('style');
        style.textContent = `
            .eas-breadcrumbs {
                padding: .35rem 1rem;
                font-size: .82rem;
                border-bottom: 1px solid var(--bs-border-color, rgba(128,128,128,.25));
                background: var(--bs-tertiary-bg, transparent);
                display: flex;
                align-items: center;
                gap: .35rem;
                flex-wrap: wrap;
            }
            .eas-breadcrumbs a { text-decoration: none; }
            .eas-breadcrumbs .eas-crumb-sep { opacity: .45; }
            .eas-breadcrumbs .eas-crumb-current { font-weight: 600; }
            .eas-palette-backdrop {
                position: fixed; inset: 0; z-index: 10500;
                background: rgba(0,0,0,.45);
                display: flex; align-items: flex-start; justify-content: center;
                padding-top: 12vh;
            }
            .eas-palette {
                width: min(620px, 92vw);
                background: var(--bs-body-bg, #fff);
                color: var(--bs-body-color, #111);
                border: 1px solid var(--bs-border-color, rgba(128,128,128,.35));
                border-radius: 10px;
                box-shadow: 0 18px 50px rgba(0,0,0,.35);
                overflow: hidden;
            }
            .eas-palette input {
                width: 100%;
                border: none; outline: none;
                background: transparent; color: inherit;
                font-size: 1.05rem;
                padding: .85rem 1rem;
                border-bottom: 1px solid var(--bs-border-color, rgba(128,128,128,.25));
            }
            .eas-palette ul {
                list-style: none; margin: 0; padding: .35rem;
                max-height: 50vh; overflow-y: auto;
            }
            .eas-palette li {
                display: flex; align-items: baseline; gap: .6rem;
                padding: .45rem .65rem;
                border-radius: 6px;
                cursor: pointer;
            }
            .eas-palette li.active {
                background: var(--bs-primary, #0d6efd);
                color: #fff;
            }
            .eas-palette li.active .eas-palette-trail { color: rgba(255,255,255,.75); }
            .eas-palette-trail {
                font-size: .75rem;
                color: var(--bs-secondary-color, #888);
                margin-left: auto;
                white-space: nowrap;
            }
            .eas-palette-empty {
                padding: 1rem; text-align: center;
                color: var(--bs-secondary-color, #888);
                font-size: .9rem;
            }
            .eas-palette-hint {
                padding: .35rem .9rem;
                font-size: .72rem;
                color: var(--bs-secondary-color, #888);
                border-top: 1px solid var(--bs-border-color, rgba(128,128,128,.25));
                display: flex; gap: 1rem;
            }
            .eas-palette-hint kbd {
                font-size: .7rem; padding: .05rem .35rem;
            }
        `;
        document.head.appendChild(style);
    }

    // ---- Breadcrumbs -------------------------------------------------------

    function pathOf(href) {
        try {
            const u = new URL(href, window.location.origin);
            return { path: u.pathname.replace(/\/+$/, '') || '/', search: u.search };
        } catch (e) {
            return null;
        }
    }

    function findCurrentEntry(entries) {
        const here = pathOf(window.location.href);
        if (!here) return null;
        let pathMatch = null;
        for (const entry of entries) {
            const target = pathOf(entry.href);
            if (!target || target.path !== here.path) continue;
            // Query-string–distinguished pages (e.g. /logs?type=audit) need
            // the search to match too; a bare path match is the fallback.
            if (target.search && target.search === here.search) return entry;
            if (!target.search && !pathMatch) pathMatch = entry;
        }
        return pathMatch;
    }

    function renderBreadcrumbs(entries) {
        if (window.location.pathname === '/') return;
        const entry = findCurrentEntry(entries);
        if (!entry || !entry.trail.length) return;
        const main = document.querySelector('main.page-shell');
        if (!main) return;

        const nav = document.createElement('nav');
        nav.className = 'eas-breadcrumbs';
        nav.setAttribute('aria-label', 'Breadcrumb');

        const frag = document.createDocumentFragment();
        const home = document.createElement('a');
        home.href = '/';
        home.innerHTML = '<i class="fas fa-gauge-high" aria-hidden="true"></i> Dashboard';
        frag.appendChild(home);

        for (const part of entry.trail) {
            const sep = document.createElement('span');
            sep.className = 'eas-crumb-sep';
            sep.textContent = '›';
            frag.appendChild(sep);
            const span = document.createElement('span');
            span.textContent = part;
            frag.appendChild(span);
        }

        const sep = document.createElement('span');
        sep.className = 'eas-crumb-sep';
        sep.textContent = '›';
        frag.appendChild(sep);
        const current = document.createElement('span');
        current.className = 'eas-crumb-current';
        current.setAttribute('aria-current', 'page');
        current.textContent = entry.label;
        frag.appendChild(current);

        nav.appendChild(frag);
        main.parentNode.insertBefore(nav, main);
    }

    // ---- Command palette ---------------------------------------------------

    function scoreEntry(entry, query) {
        // Lower is better; null means no match. Match against the label
        // first, then the trail, then the URL.
        const q = query.toLowerCase();
        const label = entry.label.toLowerCase();
        const haystacks = [
            { text: label, weight: 0 },
            { text: entry.trail.join(' ').toLowerCase(), weight: 40 },
            { text: entry.href.toLowerCase(), weight: 60 },
        ];
        let best = null;
        for (const { text, weight } of haystacks) {
            if (!text) continue;
            const idx = text.indexOf(q);
            if (idx >= 0) {
                const s = weight + idx + text.length * 0.01;
                if (best === null || s < best) best = s;
                continue;
            }
            // Subsequence fallback ("sdrdiag" → "SDR Diagnostics").
            let ti = 0, ok = true;
            for (const ch of q) {
                ti = text.indexOf(ch, ti);
                if (ti < 0) { ok = false; break; }
                ti += 1;
            }
            if (ok) {
                const s = weight + 100 + text.length * 0.01;
                if (best === null || s < best) best = s;
            }
        }
        return best;
    }

    function createPalette(entries) {
        let backdrop = null;
        let activeIdx = 0;
        let results = [];

        function close() {
            if (backdrop) {
                backdrop.remove();
                backdrop = null;
            }
        }

        function navigate(entry) {
            if (entry) window.location.href = entry.href;
        }

        function render(listEl, query) {
            results = !query
                ? entries.slice(0, 12)
                : entries
                    .map(e => ({ e, s: scoreEntry(e, query) }))
                    .filter(r => r.s !== null)
                    .sort((a, b) => a.s - b.s)
                    .slice(0, 12)
                    .map(r => r.e);
            activeIdx = 0;

            if (!results.length) {
                listEl.innerHTML = '<div class="eas-palette-empty">No matching pages</div>';
                return;
            }
            listEl.innerHTML = '';
            results.forEach((entry, i) => {
                const li = document.createElement('li');
                li.className = i === activeIdx ? 'active' : '';
                li.setAttribute('role', 'option');
                const label = document.createElement('span');
                label.textContent = entry.label;
                li.appendChild(label);
                if (entry.trail.length) {
                    const trail = document.createElement('span');
                    trail.className = 'eas-palette-trail';
                    trail.textContent = entry.trail.join(' › ');
                    li.appendChild(trail);
                }
                li.addEventListener('mouseenter', () => {
                    listEl.querySelectorAll('li').forEach(n => n.classList.remove('active'));
                    li.classList.add('active');
                    activeIdx = i;
                });
                li.addEventListener('click', () => navigate(entry));
                listEl.appendChild(li);
            });
        }

        function moveActive(listEl, delta) {
            if (!results.length) return;
            activeIdx = (activeIdx + delta + results.length) % results.length;
            listEl.querySelectorAll('li').forEach((n, i) => {
                n.classList.toggle('active', i === activeIdx);
                if (i === activeIdx) n.scrollIntoView({ block: 'nearest' });
            });
        }

        function open() {
            if (backdrop) { close(); return; }
            backdrop = document.createElement('div');
            backdrop.className = 'eas-palette-backdrop';
            backdrop.addEventListener('mousedown', (ev) => {
                if (ev.target === backdrop) close();
            });

            const box = document.createElement('div');
            box.className = 'eas-palette';
            box.setAttribute('role', 'dialog');
            box.setAttribute('aria-label', 'Page search');

            const input = document.createElement('input');
            input.type = 'text';
            input.placeholder = 'Jump to a page…';
            input.setAttribute('aria-label', 'Search pages');

            const list = document.createElement('ul');
            list.setAttribute('role', 'listbox');

            const hint = document.createElement('div');
            hint.className = 'eas-palette-hint';
            hint.innerHTML = '<span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>'
                + '<span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span>';

            input.addEventListener('input', () => render(list, input.value.trim()));
            input.addEventListener('keydown', (ev) => {
                if (ev.key === 'ArrowDown') { ev.preventDefault(); moveActive(list, 1); }
                else if (ev.key === 'ArrowUp') { ev.preventDefault(); moveActive(list, -1); }
                else if (ev.key === 'Enter') { ev.preventDefault(); navigate(results[activeIdx]); }
                else if (ev.key === 'Escape') { ev.preventDefault(); close(); }
            });

            box.appendChild(input);
            box.appendChild(list);
            box.appendChild(hint);
            backdrop.appendChild(box);
            document.body.appendChild(backdrop);
            render(list, '');
            input.focus();
        }

        document.addEventListener('keydown', (ev) => {
            if ((ev.ctrlKey || ev.metaKey) && !ev.shiftKey && !ev.altKey
                    && (ev.key === 'k' || ev.key === 'K')) {
                ev.preventDefault();
                open();
            } else if (ev.key === 'Escape' && backdrop) {
                close();
            }
        });

        return { open, close };
    }

    function addNavbarButton(palette) {
        const host = document.querySelector('.navbar .navbar-sections');
        if (!host) return;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-sm btn-outline-secondary d-none d-lg-inline-flex align-items-center gap-1 ms-2';
        btn.setAttribute('aria-label', 'Search pages (Ctrl+K)');
        btn.title = 'Search pages (Ctrl+K)';
        btn.innerHTML = '<i class="fas fa-magnifying-glass" aria-hidden="true"></i>'
            + '<kbd class="small" style="font-size:.65rem;">Ctrl K</kbd>';
        btn.addEventListener('click', palette.open);
        host.appendChild(btn);
    }

    document.addEventListener('DOMContentLoaded', () => {
        const entries = buildIndex();
        if (!entries.length) return;
        injectStyles();
        renderBreadcrumbs(entries);
        const palette = createPalette(entries);
        addNavbarButton(palette);
        window.EASCommandPalette = palette;
    });
})();
