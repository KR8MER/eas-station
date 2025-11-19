# Archived Templates

Legacy templates that are no longer rendered by Flask live in this folder so historical UI work remains documented without
cluttering the active `templates/` tree. Nothing inside this directory is imported by the application.

## Contents

- `components/navbar_old.html` – superseded RBAC-heavy navigation bar kept for reference.
- `components/page_header.html` – generic header macro that has been replaced by bespoke hero cards.
- `partials/common_head.html`, `partials/footer.html`, `partials/navbar.html` – legacy includes replaced by the consolidated
  `base.html` layout.
- `pages/system_health_old.html`, `pages/version_old.html`, `pages/admin.html.backup` – historical page layouts preserved for
  documentation only.

> **Note:** Please do not move files back out of this archive without verifying that the routing layer actually references them.
