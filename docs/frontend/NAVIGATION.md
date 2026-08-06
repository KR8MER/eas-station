# Navigation System

EAS Station™ renders every navigation surface from **one declarative registry**:
[`webapp/navigation/registry.py`](https://github.com/KR8MER/eas-station/blob/main/webapp/navigation/registry.py).

Three surfaces read that registry:

| Surface | Template | What it shows |
| --- | --- | --- |
| Top navbar | `templates/components/navbar.html` | Sections as dropdowns/links |
| Settings hub (`/settings`) | `templates/settings_hub.html` | The `settings` section as cards |
| Site map (`/navigation`) | `templates/site_navigation.html` | Every section as cards |

> **Adding a page? Edit the registry, not a template.**
> A single `NavItem` appears in all three surfaces at once, already filtered to
> the viewer's permissions.

---

## Why a registry

Before this existed the three surfaces were independent, hand-maintained copies
of the same menu, and they had drifted:

- The site map linked `/admin/users`; the settings hub linked `/admin/rbac`.
  Both routes exist and do different things, but each surface only knew about one.
- The site map listed LED Sign, VFD Display and OLED Screens — pages the navbar
  never surfaced at all.
- The navbar gated part of the Tools menu on `analytics_manage`, which is not a
  member of `PermissionDefinition` and therefore always evaluated to `False`.
- `navbar.html` had grown to 1268 lines carrying 48 inline permission tests.

Permission filtering now happens once, in Python, and is covered by tests.

---

## Information architecture

| Section | Answers | Contents |
| --- | --- | --- |
| **Dashboard** | — | Landing page (direct link) |
| **Monitor** | *What is coming in?* | Alerts, audio & radio, station hardware |
| **Broadcast** | *What is going out?* | Message builder, history, display outputs |
| **Diagnostics** | *Is it working?* | Every test **and** every health check |
| **Reports** | *What happened?* | Logs, analytics, security, data exports |
| **Settings** | *How is it configured?* | Direct link to the `/settings` hub |
| **Help** | — | Documentation, about, support |

Two deliberate choices:

**All tests live in Diagnostics.** They used to be spread across three
dropdowns — Weekly Tests under Broadcast, Audio Tests and Alert Verification
under Tools, SDR Diagnostics under Monitor — so "check whether the station is
healthy" meant opening three menus. `tests/test_navigation_registry.py` asserts
no other section carries a page with "Test" in its label.

**Settings is a link, not a dropdown.** It previously held exactly two entries:
one link to `/settings` and one button opening the Display Units modal. The
link now goes straight to the hub, and Display Units moved to the user menu —
it is per-browser personalization, not station configuration.

---

## Module layout

| Module | Contents |
| --- | --- |
| `webapp/navigation/types.py` | Node types + the filtering/resolution logic |
| `webapp/navigation/permissions.py` | Permission-name shorthands |
| `webapp/navigation/registry.py` | The navbar sections (Monitor … Help) |
| `webapp/navigation/registry_settings.py` | The Settings section (`/settings` hub) |
| `webapp/navigation/__init__.py` | `inject_navigation()` context processor |

Settings lives in its own module because it is a different concern: it renders
as hub *cards*, not a navbar dropdown. The remaining sections stay in one file
deliberately — the value of the registry is being able to read the whole
information architecture in one place.

## Node types

Defined in `webapp/navigation/types.py`. The tree is
`NavSection` → `NavGroup` → `NavItem`.

### `NavItem`

```python
NavItem(
    label="Audio Tests",                  # link text
    icon="fas fa-flask",                  # Font Awesome classes
    endpoint="audio_tests_dashboard",     # resolved via url_for (preferred)
    href="/admin/radio",                  # or a literal path
    query="?type=audit",                  # appended to endpoint-resolved URLs
    description="Shown on hub cards and the site map.",
    permissions=(RECEIVERS_VIEW,),        # ANY-of; empty = no permission gate
    requires_auth=True,                   # hide from signed-out visitors
    modal_target="globalUnitsModal",      # renders a <button> opening a modal
)
```

Prefer `endpoint` over `href`: it goes through `url_for`, so a route rename is
caught by `tests/test_navigation_registry.py` instead of silently 404-ing.

### `NavSection`

`navbar` controls presentation:

| Value | Behaviour |
| --- | --- |
| `NAVBAR_DROPDOWN` (default) | Dropdown listing the section's groups |
| `NAVBAR_LINK` | Single link to the section's own `href`/`endpoint` |
| `NAVBAR_HIDDEN` | Not in the navbar; still on the site map |

`Settings` uses `NAVBAR_LINK` while keeping a full group tree — the navbar shows
one link, the hub renders the groups as cards.

---

## Permission model

`permissions` is an **any-of** tuple; holding one of the listed permissions is
enough. Empty means no permission gate (`requires_auth` may still apply).

Filtering cascades and prunes:

- an item is dropped when the viewer lacks every listed permission
- a group with no surviving items is dropped, so no bare header renders
- a dropdown section with no surviving groups is dropped entirely

Names must be members of `PermissionDefinition` in `app_core/auth/roles.py` —
a typo would silently hide a page from everyone, so a test enforces this.

---

## Adding a page

1. Add a `NavItem` to the right `NavGroup` in `webapp/navigation/registry.py`.
2. Run the tests:

   ```bash
   python -m pytest tests/test_navigation_registry.py -q
   ```

They verify the route exists, the permission names are real, every item has a
label/icon/description, and that no hardcoded `href` crept back into the three
navigation templates.

---

## Rendered-DOM contract

`static/js/core/nav-enhance.js` builds the **Ctrl/Cmd+K command palette** and
the **breadcrumb trail** by indexing the *rendered* navbar rather than the
registry — that way both automatically respect permission-based visibility.

It walks:

```
.navbar-nav > .nav-item
    └── .dropdown-menu > li
            ├── .dropdown-header      → group label
            └── a.dropdown-item[href] → a page
```

Changing that nesting silently empties the palette and the breadcrumbs, so
`test_navbar_preserves_the_command_palette_dom_contract` guards the markers.

---

## Gotchas

**Jinja parses its tags inside HTML comments.** Writing a literal
`{% if ... %}` in an explanatory comment in `navbar.html` creates a real,
unclosed block and the template fails to compile with
`Unexpected end of template`. Describe tags in prose instead.

**The navbar template is split three ways** to stay within the size guidance in
`AGENTS.md`:

| File | Contents |
| --- | --- |
| `components/navbar.html` | Markup — brand, indicators, the registry loop |
| `components/navbar_styles.html` | Scoped CSS (stack light, aurora, clock) |
| `components/navbar_scripts.html` | Behaviour (health, WebSocket, stack light) |

The latter two are included at the end of `navbar.html`.

---

## See also

- [Component Library](COMPONENT_LIBRARY.md)
- [User Interface Guide](USER_INTERFACE_GUIDE.md)
- [Developer Guidelines](../development/AGENTS.md)
