/**
 * EAS Station™ — Settings hub search
 *
 * Search box on /settings that matches BOTH a setting's field label ("Stream
 * Bitrate") and its currently-stored value ("128"), not just the label of
 * the settings *page* it lives on (the existing Ctrl+K command palette in
 * nav-enhance.js already covers page-label search). Deliberately scoped to
 * this one page's content, not a global header search bar.
 *
 * Two data sources, both already permission-filtered server-side:
 *   - .settings-card-col elements already in the DOM (data-label/data-desc)
 *     for the existing page-card grid.
 *   - #eas-settings-search-index, a flat JSON array of
 *     {field_label, value_display, value_search, page_label, page_url, group}
 *     built by app_core.settings_search.build_settings_search_index() and
 *     embedded only on this page (unlike nav-enhance.js's settings-nav-data,
 *     which is safe to embed globally since it holds no field values).
 *
 * Matching is a small local copy of nav-enhance.js's scoreEntry() (substring
 * match, falling back to an in-order subsequence match) rather than a shared
 * import, since it's ~15 dependency-free lines and the two files have no
 * reason to load in a particular order relative to each other.
 */
(function () {
    'use strict';

    function score(haystack, query) {
        if (!haystack) return null;
        const idx = haystack.indexOf(query);
        if (idx >= 0) return idx + haystack.length * 0.01;
        let hi = 0, ok = true;
        for (const ch of query) {
            hi = haystack.indexOf(ch, hi);
            if (hi < 0) { ok = false; break; }
            hi += 1;
        }
        return ok ? 100 + haystack.length * 0.01 : null;
    }

    // core/utils.js (loaded globally in base.html, before this script) owns
    // the one true escapeHtml -- see tests/test_frontend_consistency.py's
    // test_escape_html_has_exactly_one_implementation.
    const escapeHtml = window.escapeHtml;

    document.addEventListener('DOMContentLoaded', function () {
        const input = document.getElementById('settingsSearchBox');
        const status = document.getElementById('settingsSearchStatus');
        const cardCols = Array.from(document.querySelectorAll('.settings-card-col'));
        const cardGridEmpty = document.getElementById('settingsCardGridEmpty');
        const hitsContainer = document.getElementById('settingsSearchHits');
        const indexEl = document.getElementById('eas-settings-search-index');
        if (!input || !cardGridEmpty || !hitsContainer) return;

        let fieldIndex = [];
        try {
            fieldIndex = indexEl ? JSON.parse(indexEl.textContent) : [];
        } catch (e) {
            fieldIndex = [];
        }

        function filterCards(query) {
            let visible = 0;
            for (const col of cardCols) {
                const matches = !query
                    || score(col.dataset.label || '', query) !== null
                    || score(col.dataset.desc || '', query) !== null;
                col.hidden = !matches;
                if (matches) visible += 1;
            }
            cardGridEmpty.hidden = !(query && visible === 0);
            if (query && visible === 0) {
                cardGridEmpty.querySelector('span').textContent = query;
            }
            return visible;
        }

        function matchFields(query) {
            const scored = [];
            for (const entry of fieldIndex) {
                const labelScore = score((entry.field_label || '').toLowerCase(), query);
                const valueScore = score((entry.value_search || '').toLowerCase(), query);
                const pageScore = score((entry.page_label || '').toLowerCase(), query);
                const best = [labelScore, valueScore === null ? null : valueScore + 20,
                    pageScore === null ? null : pageScore + 40]
                    .filter((s) => s !== null);
                if (best.length) scored.push({ entry, s: Math.min(...best) });
            }
            scored.sort((a, b) => a.s - b.s);
            return scored.slice(0, 25).map((r) => r.entry);
        }

        function renderHits(hits) {
            if (!hits.length) {
                hitsContainer.hidden = true;
                hitsContainer.innerHTML = '';
                return;
            }
            hitsContainer.hidden = false;
            hitsContainer.innerHTML = hits.map((h) => `
                <a class="settings-search-hit" href="${escapeHtml(h.page_url)}">
                    <span>
                        <span class="settings-search-hit-field">${escapeHtml(h.field_label)}</span>:
                        <span class="settings-search-hit-value">${escapeHtml(h.value_display)}</span>
                    </span>
                    <span class="settings-search-hit-page">${escapeHtml(h.group)} &rsaquo; ${escapeHtml(h.page_label)}</span>
                </a>
            `).join('');
        }

        function runSearch() {
            const query = input.value.trim().toLowerCase();
            if (!query) {
                filterCards('');
                renderHits([]);
                status.textContent = '';
                return;
            }
            const visiblePages = filterCards(query);
            const hits = matchFields(query);
            renderHits(hits);
            const parts = [];
            parts.push(`${visiblePages} page${visiblePages === 1 ? '' : 's'}`);
            if (hits.length) parts.push(`${hits.length} matching field${hits.length === 1 ? '' : 's'}`);
            status.textContent = parts.join(', ');
        }

        input.addEventListener('input', runSearch);
    });
})();
