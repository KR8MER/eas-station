/**
 * EAS Station™ — Audio Archives (/admin/audio/archives)
 *
 * Renders one card per configured audio source with four tabs: Settings,
 * Files, Song History and Stats.  Tab contents are fetched the first time a
 * tab is shown.
 *
 * Sources are addressed by their index in the loaded array (`data-idx`) rather
 * than by name, so a source name containing quotes or spaces cannot break the
 * generated markup or the event handlers.
 */
(function () {
    'use strict';

    /** Sources from the last /api/audio/archives/sources call, index = data-idx. */
    let sources = [];

    /** Panel keys already fetched, e.g. "0:files". */
    const loaded = new Set();

    /** Source index the purge modal is currently acting on. */
    let purgeIdx = null;

    const esc = (v) => (window.escapeHtml ? window.escapeHtml(v) : String(v == null ? '' : v));
    const notify = (msg, ok = true) => window.showToast(msg, ok ? 'success' : 'error');

    // ---------------------------------------------------------------------
    // Formatting helpers
    // ---------------------------------------------------------------------

    function fmtBytes(n) {
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let u = 0;
        while (n >= 1024 && u < units.length - 1) { n /= 1024; u++; }
        return n.toFixed(1) + ' ' + units[u];
    }

    function fmtDuration(secs) {
        if (secs === null || secs === undefined) return '—';
        secs = Math.round(secs);
        if (secs >= 3600) {
            return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
        }
        return `${Math.floor(secs / 60)}m ${secs % 60}s`;
    }

    const fmtTs = (iso) => (iso ? new Date(iso).toLocaleString() : '—');

    /** VAST <Duration> is "HH:MM:SS(.mmm)" -- convert to seconds for fmtDuration(). */
    function vastDurationToSecs(d) {
        const m = /^(\d+):(\d{2}):(\d{2})/.exec(d || '');
        if (!m) return null;
        return parseInt(m[1], 10) * 3600 + parseInt(m[2], 10) * 60 + parseInt(m[3], 10);
    }
    const gbToBytes = (gb) => Math.round(parseFloat(gb || 0) * 1073741824);
    const bytesToGb = (b) => (b / 1073741824).toFixed(2);

    async function api(method, url, body) {
        const opts = { method, headers: { 'Content-Type': 'application/json' } };
        if (body !== undefined) opts.body = JSON.stringify(body);
        const response = await fetch(url, opts);
        return response.json();
    }

    /** Placeholder shown while a tab pane loads. */
    const loadingHtml = (label) =>
        `<div class="text-center text-muted py-4"><span class="spinner"></span> Loading ${label}…</div>`;

    const emptyHtml = (icon, text) =>
        `<div class="text-center text-muted py-4"><i class="fas ${icon} fa-2x mb-2 d-block opacity-50"></i>${esc(text)}</div>`;

    const errorHtml = (what, err) =>
        `<div class="alert alert-danger mb-0">Failed to load ${esc(what)}: ${esc(err)}</div>`;

    function artworkHtml(url) {
        return url
            ? `<img src="${esc(url)}" class="arch-artwork" alt="" onerror="this.style.display='none'">`
            : '<div class="arch-artwork arch-artwork-empty"><i class="fas fa-music"></i></div>';
    }

    // ---------------------------------------------------------------------
    // Card rendering
    // ---------------------------------------------------------------------

    function cardHtml(s, i) {
        const arch = s.archive || {};
        const on = !!arch.enabled;
        const diskBytes = s.disk_bytes || 0;
        const maxBytes = arch.max_disk_bytes || 0;
        const pct = maxBytes > 0 ? Math.min(100, (diskBytes / maxBytes) * 100) : 0;
        const quotaClass = pct > 90 ? 'danger' : pct > 70 ? 'warn' : '';

        const quotaHtml = maxBytes > 0 ? `
            <span class="arch-quota" title="${pct.toFixed(0)}% of the ${bytesToGb(maxBytes)} GB quota">
                <span class="arch-quota-track">
                    <span class="arch-quota-fill ${quotaClass}" style="width:${pct.toFixed(1)}%"></span>
                </span>
                <span class="text-muted small">${pct.toFixed(0)}%</span>
            </span>` : '';

        return `
<div class="card shadow-sm mb-3" data-idx="${i}">
  <div class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
    <button class="btn btn-link text-decoration-none p-0 text-start d-flex align-items-center gap-2"
            type="button" data-bs-toggle="collapse" data-bs-target="#arch-body-${i}"
            aria-expanded="false" aria-controls="arch-body-${i}">
      <i class="fas fa-chevron-right arch-chevron"></i>
      <span class="fw-semibold">${esc(s.source_name)}</span>
      <span class="text-muted small">${esc(s.source_type || '—')}</span>
      <span class="status-badge ${on ? 'success' : 'secondary'}">${on ? 'Archiving on' : 'Archiving off'}</span>
    </button>
    <div class="d-flex align-items-center gap-3 flex-wrap">
      <span class="text-muted small">
        <i class="fas fa-hard-drive me-1"></i>${esc(s.disk_bytes_human || '0 B')}
        &bull; ${s.disk_files || 0} file${s.disk_files === 1 ? '' : 's'}
      </span>
      ${quotaHtml}
    </div>
  </div>

  <div class="collapse" id="arch-body-${i}">
    <div class="card-body">
      <ul class="nav nav-tabs mb-3" role="tablist">
        ${tabHtml(i, 'settings', 'fa-sliders', 'Settings', true)}
        ${tabHtml(i, 'files', 'fa-folder-open', 'Files', false)}
        ${tabHtml(i, 'history', 'fa-music', 'Song History', false)}
        ${tabHtml(i, 'stats', 'fa-chart-bar', 'Stats', false)}
      </ul>
      <div class="tab-content">
        <div class="tab-pane fade show active" id="arch-settings-${i}" role="tabpanel">${settingsHtml(s, i)}</div>
        <div class="tab-pane fade" id="arch-files-${i}" role="tabpanel">${loadingHtml('files')}</div>
        <div class="tab-pane fade" id="arch-history-${i}" role="tabpanel">${historyShellHtml(i)}</div>
        <div class="tab-pane fade" id="arch-stats-${i}" role="tabpanel">${loadingHtml('stats')}</div>
      </div>
    </div>
  </div>
</div>`;
    }

    function tabHtml(i, key, icon, label, active) {
        return `
        <li class="nav-item" role="presentation">
          <button class="nav-link ${active ? 'active' : ''}" data-bs-toggle="tab"
                  data-bs-target="#arch-${key}-${i}" data-tab="${key}" data-idx="${i}"
                  type="button" role="tab">
            <i class="fas ${icon} me-1"></i>${label}
          </button>
        </li>`;
    }

    function settingsHtml(s, i) {
        const a = s.archive || {};
        const isMp3 = (a.format || 'wav') === 'mp3';
        return `
<form data-action="save" data-idx="${i}">
  <div class="row g-3">
    <div class="col-12">
      <div class="form-check form-switch">
        <input class="form-check-input" type="checkbox" role="switch"
               id="arch-enabled-${i}" name="enabled" ${a.enabled ? 'checked' : ''}>
        <label class="form-check-label" for="arch-enabled-${i}">Enable archiving for this source</label>
      </div>
      <div class="form-text">Saving with this on starts the archiver immediately; turning it off stops it.</div>
    </div>

    <div class="col-sm-6 col-lg-4">
      <label class="form-label" for="arch-outdir-${i}">Output directory</label>
      <input type="text" class="form-control" id="arch-outdir-${i}" name="output_dir" value="${esc(a.output_dir || 'archives')}">
      <div class="form-text">Relative paths resolve against the install directory.</div>
    </div>

    <div class="col-sm-6 col-lg-4">
      <label class="form-label" for="arch-seg-${i}">Segment length (minutes)</label>
      <input type="number" class="form-control" id="arch-seg-${i}" name="segment_minutes"
             min="1" max="1440" value="${Math.round((a.segment_duration_seconds || 3600) / 60)}">
      <div class="form-text">One file per segment, grouped into a folder per day.</div>
    </div>

    <div class="col-sm-6 col-lg-4">
      <label class="form-label" for="arch-ret-${i}">Retain for (days)</label>
      <input type="number" class="form-control" id="arch-ret-${i}" name="retention_days" min="0" value="${a.retention_days}">
      <div class="form-text">0 keeps recordings forever.</div>
    </div>

    <div class="col-sm-6 col-lg-4">
      <label class="form-label" for="arch-quota-${i}">Disk quota (GB)</label>
      <input type="number" class="form-control" id="arch-quota-${i}" name="max_disk_gb"
             min="0" step="0.1" value="${bytesToGb(a.max_disk_bytes || 0)}">
      <div class="form-text">0 is unlimited. Oldest days are removed first.</div>
    </div>

    <div class="col-sm-6 col-lg-4">
      <label class="form-label" for="arch-fmt-${i}">Format</label>
      <select class="form-select" id="arch-fmt-${i}" name="format" data-action="format">
        <option value="wav" ${isMp3 ? '' : 'selected'}>WAV (no extra dependencies)</option>
        <option value="mp3" ${isMp3 ? 'selected' : ''}>MP3 (requires FFmpeg)</option>
      </select>
    </div>

    <div class="col-sm-6 col-lg-4 arch-bitrate" ${isMp3 ? '' : 'hidden'}>
      <label class="form-label" for="arch-br-${i}">MP3 bitrate (kbps)</label>
      <input type="number" class="form-control" id="arch-br-${i}" name="bitrate"
             min="64" max="320" step="32" value="${a.bitrate || 128}">
    </div>

    <div class="col-sm-6 col-lg-4">
      <label class="form-label" for="arch-sil-${i}">Silence threshold</label>
      <input type="number" class="form-control" id="arch-sil-${i}" name="silence_threshold"
             min="0" max="1" step="0.001" value="${a.silence_threshold != null ? a.silence_threshold : 0}">
      <div class="form-text">Skip segments quieter than this RMS level. 0 disables; 0.005 drops dead air.</div>
    </div>
  </div>

  <hr class="my-3">

  <div class="d-flex flex-wrap gap-2 align-items-center">
    <button type="submit" class="btn btn-primary"><i class="fas fa-save me-1"></i>Save Settings</button>
    <button type="button" class="btn btn-outline-success" data-action="start" data-idx="${i}">
      <i class="fas fa-play me-1"></i>Start Now
    </button>
    <button type="button" class="btn btn-outline-warning" data-action="stop" data-idx="${i}">
      <i class="fas fa-stop me-1"></i>Stop
    </button>
    <button type="button" class="btn btn-outline-danger ms-auto" data-action="purge" data-idx="${i}">
      <i class="fas fa-trash me-1"></i>Delete Recordings…
    </button>
  </div>

  <div class="text-muted small mt-3">
    <i class="fas fa-clock me-1"></i>Last archived file: ${esc(fmtTs(s.newest_file_iso))}
  </div>
</form>`;
    }

    function historyShellHtml(i) {
        return `
<div class="d-flex flex-wrap gap-2 align-items-center mb-3">
  <div class="input-group input-group-sm arch-search">
    <span class="input-group-text"><i class="fas fa-search"></i></span>
    <input type="text" class="form-control" data-action="history-search" data-idx="${i}"
           placeholder="Search title, artist, album…" aria-label="Search song history">
  </div>
  <select class="form-select form-select-sm w-auto" data-action="history-limit" data-idx="${i}"
          aria-label="Number of entries">
    <option value="20">20</option>
    <option value="50">50</option>
    <option value="100" selected>100</option>
    <option value="200">200</option>
    <option value="all">All</option>
  </select>
  <span class="text-muted small" data-role="history-count"></span>
  <div class="ms-auto d-flex gap-2">
    <button type="button" class="btn btn-sm btn-outline-warning" data-action="clean-junk" data-idx="${i}"
            title="Permanently delete base64 blob entries from the history database">
      <i class="fas fa-filter me-1"></i>Clean Junk
    </button>
    <button type="button" class="btn btn-sm btn-outline-danger" data-action="clear-history" data-idx="${i}">
      <i class="fas fa-trash me-1"></i>Clear History
    </button>
  </div>
</div>
<div data-role="history-body">${loadingHtml('history')}</div>`;
    }

    // ---------------------------------------------------------------------
    // Loading
    // ---------------------------------------------------------------------

    const pane = (i, key) => document.getElementById(`arch-${key}-${i}`);

    /**
     * Reload every card.
     *
     * @param {number|null} keepOpen Source index to re-expand afterwards, so a
     *   save does not collapse the card the user is working in.
     */
    async function loadSources(keepOpen = null) {
        const container = document.getElementById('sources-container');
        container.innerHTML = loadingHtml('sources');
        loaded.clear();

        let data;
        try {
            data = await api('GET', '/api/audio/archives/sources');
        } catch (err) {
            container.innerHTML = errorHtml('sources', err);
            return;
        }

        sources = data.sources || [];
        if (!sources.length) {
            container.innerHTML =
                '<div class="alert alert-info mb-0">No audio sources are configured yet. ' +
                'Add one on the <a href="/admin/audio-sources" class="alert-link">Audio Streams</a> page.</div>';
            document.getElementById('summary-row').hidden = true;
            return;
        }

        container.innerHTML = sources.map(cardHtml).join('');

        const totalDisk = sources.reduce((a, s) => a + (s.disk_bytes || 0), 0);
        const totalFiles = sources.reduce((a, s) => a + (s.disk_files || 0), 0);
        const enabled = sources.filter((s) => s.archive && s.archive.enabled).length;
        document.getElementById('sum-disk').textContent = fmtBytes(totalDisk);
        document.getElementById('sum-files').textContent = totalFiles.toLocaleString();
        document.getElementById('sum-enabled').textContent = `${enabled} / ${sources.length}`;
        document.getElementById('summary-row').hidden = false;

        if (keepOpen !== null && document.getElementById(`arch-body-${keepOpen}`)) {
            bootstrap.Collapse.getOrCreateInstance(document.getElementById(`arch-body-${keepOpen}`)).show();
        }
    }

    async function loadFiles(i) {
        const body = pane(i, 'files');
        const name = sources[i].source_name;
        let data;
        try {
            data = await api('GET', `/api/audio/archives/${encodeURIComponent(name)}/files`);
        } catch (err) {
            body.innerHTML = errorHtml('files', err);
            return;
        }

        const dates = data.dates || [];
        if (!dates.length) {
            body.innerHTML = emptyHtml('fa-folder-open', 'No archived files yet.');
            return;
        }

        let html = `
<div class="table-responsive">
<table class="table eas-table table-sm mb-0">
  <thead><tr>
    <th>Date / File</th>
    <th class="d-none d-sm-table-cell">Size</th>
    <th>Duration</th>
    <th class="d-none d-md-table-cell">Modified</th>
    <th class="text-end">Actions</th>
  </tr></thead>`;

        dates.forEach((d, di) => {
            const totalSize = d.files.reduce((a, f) => a + f.size_bytes, 0);
            const totalDur = d.total_duration_seconds != null
                ? d.total_duration_seconds
                : d.files.reduce((a, f) => a + (f.duration_seconds || 0), 0);
            html += `
  <tbody>
    <tr class="arch-date-row table-secondary" data-action="toggle-date" data-group="${i}-${di}">
      <td colspan="2">
        <i class="fas fa-chevron-right arch-chevron me-2"></i>
        <strong>${esc(d.date)}</strong>
        <span class="text-muted ms-2">${d.files.length} file${d.files.length === 1 ? '' : 's'}</span>
      </td>
      <td class="text-muted">${esc(fmtDuration(totalDur))}</td>
      <td class="d-none d-md-table-cell"></td>
      <td class="text-end text-muted">${esc(fmtBytes(totalSize))}</td>
    </tr>
  </tbody>
  <tbody class="arch-date-files" id="arch-dg-${i}-${di}" hidden>`;

            for (const f of d.files) {
                const url = `/api/audio/archives/${encodeURIComponent(name)}/files/`
                    + `${encodeURIComponent(d.date)}/${encodeURIComponent(f.filename)}`;
                html += `
    <tr>
      <td class="ps-4 text-break-anywhere"><i class="fas fa-file-audio text-muted me-2"></i>${esc(f.filename)}</td>
      <td class="text-muted d-none d-sm-table-cell">${esc(f.size_human)}</td>
      <td class="text-muted">${esc(fmtDuration(f.duration_seconds))}</td>
      <td class="text-muted d-none d-md-table-cell">${esc(fmtTs(f.mtime))}</td>
      <td class="text-end text-nowrap">
        <button type="button" class="btn btn-sm btn-link p-1" title="Play"
                data-action="play" data-url="${esc(url)}"
                data-label="${esc(name + ' / ' + d.date + ' / ' + f.filename)}">
          <i class="fas fa-play-circle"></i>
        </button>
        <a href="${esc(url)}?download=1" class="btn btn-sm btn-link p-1" title="Download">
          <i class="fas fa-download"></i>
        </a>
      </td>
    </tr>`;
            }
            html += '\n  </tbody>';
        });

        body.innerHTML = html + '\n</table>\n</div>';
    }

    async function loadHistory(i) {
        const root = pane(i, 'history');
        const body = root.querySelector('[data-role="history-body"]');
        const countEl = root.querySelector('[data-role="history-count"]');
        const name = sources[i].source_name;

        const limit = root.querySelector('[data-action="history-limit"]').value;
        const search = root.querySelector('[data-action="history-search"]').value.trim();

        let url = `/api/audio/archives/${encodeURIComponent(name)}/metadata-log?limit=${encodeURIComponent(limit)}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;

        let data;
        try {
            data = await api('GET', url);
        } catch (err) {
            body.innerHTML = errorHtml('history', err);
            return;
        }

        const entries = data.entries || [];
        const junk = data.junk_hidden || 0;
        countEl.textContent = entries.length
            ? `${entries.length} result${entries.length === 1 ? '' : 's'}${junk ? ` · ${junk} junk hidden` : ''}`
            : '';

        if (!entries.length) {
            body.innerHTML = emptyHtml(
                'fa-music',
                search
                    ? 'No results match your search.'
                    : 'No song history yet. Entries appear when the audio service sees ICY stream metadata change.'
            );
            return;
        }

        let html = `
<div class="table-responsive">
<table class="table eas-table table-sm mb-0">
  <thead><tr>
    <th></th><th>Time</th><th>Title</th>
    <th class="d-none d-sm-table-cell">Artist</th>
    <th class="d-none d-md-table-cell">Album</th>
    <th class="d-none d-sm-table-cell">Duration</th>
    <th></th>
  </tr></thead>
  <tbody>`;

        for (const e of entries) {
            const label = e.title ? `Ad: ${e.title}` : 'Ad URL';
            // The action-column icon button below is a secondary/duplicate
            // trigger -- the primary one is the "Ad URL" text itself in the
            // title cell (see the no-title branch below), since that's the
            // prominent, obviously-labeled element a user actually clicks.
            // Before this fix the title cell only rendered a plain <span>
            // with no click handler at all, so clicking the visible "Ad
            // URL" text did nothing; this tiny icon, easy to miss off in
            // its own column, was the only thing that actually worked.
            const adBtn = e.stream_url
                ? `<button type="button" class="btn btn-sm btn-link p-1 text-warning" title="Resolve and play this ad/stream URL"
                           data-action="resolve" data-url="${esc(e.stream_url)}" data-label="${esc(label)}">
                     <i class="fas fa-ad"></i>
                   </button>`
                : '';
            let title;
            if (e.title) {
                title = esc(e.title);
            } else if (e.display) {
                title = `<em>${esc(e.display)}</em>`;
            } else if (e.stream_url) {
                title = `<button type="button" class="btn btn-sm btn-link p-0 text-warning text-decoration-none" title="Resolve and play this ad/stream URL"
                                 data-action="resolve" data-url="${esc(e.stream_url)}" data-label="${esc(label)}">
                             <i class="fas fa-ad me-1"></i>Ad URL
                           </button>`;
            } else {
                title = '<span class="text-muted">—</span>';
            }

            html += `
    <tr>
      <td>${artworkHtml(e.artwork_url)}</td>
      <td class="text-muted text-nowrap">${esc(fmtTs(e.timestamp))}</td>
      <td class="text-break-anywhere">${title}</td>
      <td class="d-none d-sm-table-cell text-break-anywhere">${e.artist ? esc(e.artist) : '<span class="text-muted">—</span>'}</td>
      <td class="d-none d-md-table-cell text-break-anywhere">${e.album ? esc(e.album) : '<span class="text-muted">—</span>'}</td>
      <td class="d-none d-sm-table-cell text-muted">${esc(e.length || '—')}</td>
      <td class="text-end">${adBtn}</td>
    </tr>`;
        }

        body.innerHTML = html + '\n  </tbody>\n</table>\n</div>';
    }

    async function loadStats(i) {
        const body = pane(i, 'stats');
        const name = sources[i].source_name;
        let d;
        try {
            d = await api('GET', `/api/audio/archives/${encodeURIComponent(name)}/stats`);
        } catch (err) {
            body.innerHTML = errorHtml('stats', err);
            return;
        }

        if (!d.total_files && !(d.top_songs || []).length) {
            body.innerHTML = emptyHtml('fa-chart-bar', 'No archive data yet.');
            return;
        }

        const tile = (label, value) => `
      <div class="col-6 col-md-3">
        <div class="arch-stat">
          <div class="text-muted small">${esc(label)}</div>
          <div class="arch-stat-value">${esc(value)}</div>
        </div>
      </div>`;

        let html = '<div class="row g-3 mb-4">'
            + tile('Total files', d.total_files)
            + tile('Total size', d.total_bytes_human)
            + tile('Total recorded', d.total_duration_human)
            + (d.oldest_date ? tile('Oldest day', d.oldest_date) : '')
            + (d.newest_date ? tile('Newest day', d.newest_date) : '')
            + '</div>';

        if ((d.dates || []).length) {
            html += '<h3 class="h6 text-muted mb-2">Recording History</h3>'
                + '<div class="table-responsive"><table class="table eas-table table-sm mb-4">'
                + '<thead><tr><th>Date</th><th>Files</th><th>Duration</th><th>Size</th></tr></thead><tbody>'
                + d.dates.map((r) => `<tr>
                    <td>${esc(r.date)}</td>
                    <td class="text-muted">${r.file_count}</td>
                    <td class="text-muted">${esc(r.duration_human)}</td>
                    <td class="text-muted">${esc(r.total_bytes_human)}</td>
                   </tr>`).join('')
                + '</tbody></table></div>';
        }

        if ((d.top_songs || []).length) {
            html += '<h3 class="h6 text-muted mb-2">Top Songs</h3>'
                + '<div class="table-responsive"><table class="table eas-table table-sm mb-4">'
                + '<thead><tr><th></th><th>Title</th><th>Artist</th><th class="text-end">Plays</th></tr></thead><tbody>'
                + d.top_songs.map((s) => `<tr>
                    <td>${artworkHtml(s.artwork_url)}</td>
                    <td class="text-break-anywhere">${s.title ? esc(s.title) : '<span class="text-muted">—</span>'}</td>
                    <td class="text-muted text-break-anywhere">${esc(s.artist || '—')}</td>
                    <td class="text-end text-muted">${s.count}</td>
                   </tr>`).join('')
                + '</tbody></table></div>';
        }

        if ((d.top_artists || []).length) {
            html += '<h3 class="h6 text-muted mb-2">Top Artists</h3>'
                + '<div class="table-responsive"><table class="table eas-table table-sm mb-0">'
                + '<thead><tr><th>Artist</th><th class="text-end">Plays</th></tr></thead><tbody>'
                + d.top_artists.map((a) => `<tr>
                    <td class="text-break-anywhere">${esc(a.artist)}</td>
                    <td class="text-end text-muted">${a.count}</td>
                   </tr>`).join('')
                + '</tbody></table></div>';
        }

        body.innerHTML = html;
    }

    const LOADERS = { files: loadFiles, history: loadHistory, stats: loadStats };

    function ensureLoaded(i, tab) {
        const key = `${i}:${tab}`;
        if (!LOADERS[tab] || loaded.has(key)) return;
        loaded.add(key);
        LOADERS[tab](i);
    }

    // ---------------------------------------------------------------------
    // Actions
    // ---------------------------------------------------------------------

    async function saveSettings(form, i) {
        const name = sources[i].source_name;
        const fd = new FormData(form);
        const enabled = fd.get('enabled') === 'on';
        const body = {
            enabled,
            output_dir: fd.get('output_dir'),
            segment_duration_seconds: parseInt(fd.get('segment_minutes') || 60, 10) * 60,
            retention_days: parseInt(fd.get('retention_days') || 7, 10),
            max_disk_bytes: gbToBytes(fd.get('max_disk_gb')),
            format: fd.get('format'),
            bitrate: parseInt(fd.get('bitrate') || 128, 10),
            silence_threshold: parseFloat(fd.get('silence_threshold') || 0),
        };

        try {
            const saved = await api('POST', `/api/audio/archives/${encodeURIComponent(name)}/settings`, body);
            if (!saved.saved) {
                notify('Save failed: ' + (saved.error || 'unknown error'), false);
                return;
            }

            if (enabled) {
                const r = await api('POST', `/api/audio/archives/${encodeURIComponent(name)}/start`, {});
                const ok = !!(r.result && r.result.success);
                notify(ok
                    ? `Settings saved. Archiving is running for ${name}.`
                    : `Settings saved, but the archiver did not start: ${(r.result || {}).message || r.error || 'unknown error'}`,
                    ok);
            } else {
                await api('POST', `/api/audio/archives/${encodeURIComponent(name)}/stop`, {});
                notify(`Settings saved. Archiving is off for ${name}.`);
            }
            await loadSources(i);
        } catch (err) {
            notify('Error: ' + err, false);
        }
    }

    async function startStop(i, action) {
        const name = sources[i].source_name;
        try {
            const r = await api('POST', `/api/audio/archives/${encodeURIComponent(name)}/${action}`, {});
            const ok = !!(r.result && r.result.success);
            const verb = action === 'start' ? 'started' : 'stopped';
            notify(ok
                ? `Archiver ${verb} for ${name}`
                : `Could not ${action} the archiver: ${(r.result || {}).message || r.error || 'unknown error'}`,
                ok);
            if (ok) await loadSources(i);
        } catch (err) {
            notify('Error: ' + err, false);
        }
    }

    async function runPurge(i, daysOlderThan) {
        const name = sources[i].source_name;
        const body = daysOlderThan > 0 ? { days_older_than: daysOlderThan } : {};
        try {
            const r = await api('POST', `/api/audio/archives/${encodeURIComponent(name)}/purge`, body);
            if (r.error) {
                notify('Delete failed: ' + r.error, false);
                return;
            }
            notify(`Deleted ${r.files_deleted} file(s), freeing ${r.bytes_freed_human}`);
            await loadSources(i);
        } catch (err) {
            notify('Error: ' + err, false);
        }
    }

    async function clearHistory(i) {
        const name = sources[i].source_name;
        if (!confirm(`Clear all song history for "${name}"?\nThis cannot be undone.`)) return;
        try {
            const r = await api('DELETE', `/api/audio/archives/${encodeURIComponent(name)}/metadata-log`);
            if (r.error) {
                notify('Clear failed: ' + r.error, false);
                return;
            }
            notify(`Cleared ${r.deleted} history entry(s) for ${name}`);
            loadHistory(i);
        } catch (err) {
            notify('Error: ' + err, false);
        }
    }

    async function cleanJunk(i) {
        const name = sources[i].source_name;
        if (!confirm(`Remove base64-blob junk entries from the history for "${name}"?\n`
            + 'Commercials, promos, and station IDs are not affected.')) return;
        try {
            const r = await api('POST', `/api/audio/archives/${encodeURIComponent(name)}/metadata-log/clean-junk`);
            if (r.error) {
                notify('Clean failed: ' + r.error, false);
                return;
            }
            notify(r.deleted ? `Removed ${r.deleted} junk entry(s) for ${name}` : `No junk entries found for ${name}`);
            loadHistory(i);
        } catch (err) {
            notify('Error: ' + err, false);
        }
    }

    // ---------------------------------------------------------------------
    // Player bar
    // ---------------------------------------------------------------------

    function play(url, label) {
        const bar = document.getElementById('player-bar');
        const audio = document.getElementById('player-audio');
        audio.src = url;
        document.getElementById('player-label').textContent = label;
        bar.hidden = false;
        audio.play().catch(() => { /* user gesture may be required */ });
    }

    function closePlayer() {
        const audio = document.getElementById('player-audio');
        audio.pause();
        audio.removeAttribute('src');
        document.getElementById('player-bar').hidden = true;
    }

    async function resolveAndPlay(btn, url, label) {
        const icon = btn.querySelector('i');
        const original = icon.className;
        icon.className = 'fas fa-spinner fa-spin';
        btn.disabled = true;
        try {
            const r = await api('POST', '/api/audio/archives/resolve-stream-url', { url });
            if (r.audio_url) {
                // Prefer the ad server's own title when it gave us one --
                // some (e.g. Triton) only return an internal creative ID,
                // but others return a genuinely useful name, so use it when
                // present rather than the generic "Ad URL" placeholder.
                let playLabel = r.ad_title ? `Ad: ${r.ad_title}` : label;
                const secs = vastDurationToSecs(r.duration);
                if (secs !== null) playLabel += ` (${fmtDuration(secs)})`;
                play(r.audio_url, playLabel);
            } else {
                notify(r.error || 'No playable audio found at that URL', false);
            }
        } catch (err) {
            notify('Resolve failed: ' + err, false);
        } finally {
            icon.className = original;
            btn.disabled = false;
        }
    }

    // ---------------------------------------------------------------------
    // Wiring
    // ---------------------------------------------------------------------

    function openPurgeModal(i) {
        purgeIdx = i;
        document.getElementById('purgeSourceName').textContent = sources[i].source_name;
        document.querySelector('input[name="purgeScope"][value="old"]').checked = true;
        document.getElementById('purgeDays').value = 7;
        syncPurgeModal();
        bootstrap.Modal.getOrCreateInstance(document.getElementById('purgeModal')).show();
    }

    function syncPurgeModal() {
        const all = document.querySelector('input[name="purgeScope"][value="all"]').checked;
        document.getElementById('purgeDaysWrap').hidden = all;
        document.getElementById('purgeConfirm').classList.toggle('btn-danger', all);
        document.getElementById('purgeConfirm').classList.toggle('btn-warning', !all);
    }

    const historyDebounce = {};

    function init() {
        document.getElementById('refreshBtn').addEventListener('click', loadSources);

        const container = document.getElementById('sources-container');

        container.addEventListener('click', (evt) => {
            const el = evt.target.closest('[data-action]');
            if (!el) return;
            const idx = el.dataset.idx !== undefined ? parseInt(el.dataset.idx, 10) : null;

            switch (el.dataset.action) {
                case 'start':
                case 'stop':
                    startStop(idx, el.dataset.action);
                    break;
                case 'purge':
                    openPurgeModal(idx);
                    break;
                case 'clear-history':
                    clearHistory(idx);
                    break;
                case 'clean-junk':
                    cleanJunk(idx);
                    break;
                case 'play':
                    play(el.dataset.url, el.dataset.label);
                    break;
                case 'resolve':
                    resolveAndPlay(el, el.dataset.url, el.dataset.label);
                    break;
                case 'toggle-date': {
                    const group = document.getElementById('arch-dg-' + el.dataset.group);
                    group.hidden = !group.hidden;
                    el.querySelector('.arch-chevron').classList.toggle('open', !group.hidden);
                    break;
                }
                default:
                    break;
            }
        });

        container.addEventListener('submit', (evt) => {
            const form = evt.target.closest('form[data-action="save"]');
            if (!form) return;
            evt.preventDefault();
            saveSettings(form, parseInt(form.dataset.idx, 10));
        });

        container.addEventListener('change', (evt) => {
            const el = evt.target.closest('[data-action]');
            if (!el) return;
            if (el.dataset.action === 'format') {
                const wrap = el.closest('.row').querySelector('.arch-bitrate');
                wrap.hidden = el.value !== 'mp3';
            } else if (el.dataset.action === 'history-limit') {
                loadHistory(parseInt(el.dataset.idx, 10));
            }
        });

        container.addEventListener('input', (evt) => {
            const el = evt.target.closest('[data-action="history-search"]');
            if (!el) return;
            const i = parseInt(el.dataset.idx, 10);
            clearTimeout(historyDebounce[i]);
            historyDebounce[i] = setTimeout(() => loadHistory(i), 350);
        });

        // Lazy-load a tab's contents the first time it is shown.
        container.addEventListener('shown.bs.tab', (evt) => {
            ensureLoaded(parseInt(evt.target.dataset.idx, 10), evt.target.dataset.tab);
        });

        // Rotate the card chevron with the collapse state.
        container.addEventListener('show.bs.collapse', (evt) => {
            evt.target.closest('.card').querySelector('.card-header .arch-chevron').classList.add('open');
        });
        container.addEventListener('hide.bs.collapse', (evt) => {
            evt.target.closest('.card').querySelector('.card-header .arch-chevron').classList.remove('open');
        });

        document.getElementById('player-close').addEventListener('click', closePlayer);

        document.querySelectorAll('input[name="purgeScope"]').forEach((el) => {
            el.addEventListener('change', syncPurgeModal);
        });
        document.getElementById('purgeConfirm').addEventListener('click', () => {
            const all = document.querySelector('input[name="purgeScope"][value="all"]').checked;
            const days = all ? 0 : Math.max(1, parseInt(document.getElementById('purgeDays').value, 10) || 7);
            bootstrap.Modal.getOrCreateInstance(document.getElementById('purgeModal')).hide();
            runPurge(purgeIdx, days);
        });

        loadSources();
    }

    document.addEventListener('DOMContentLoaded', init);
})();
