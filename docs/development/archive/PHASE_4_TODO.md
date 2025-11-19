# Phase 4: Admin.html Migration & Final Integration - Todo List

## Overview
Complete the UI modernization by migrating admin.html and fixing remaining issues.

**Current Status:** 35% Complete (Updated November 2025)
**Estimated Completion:** 14/40 hours invested

## Priority 1: Quick Fixes
- [x] Fix help.html Documentation Center white text issue (PR #295)
- [ ] Test all new components in production
- [ ] Verify dark mode across all pages

## Priority 2: Admin.html Migration (5,614 lines)
### Component Standardization (Completed)
- [x] Standardize all buttons (17 instances across all tabs)
- [x] Standardize all alerts (17 instances across all tabs)
- [x] Update showStatus() function mapping
- [x] Remove all btn-custom and alert-*-custom usage
- [x] 100% design system compliance for buttons and alerts

### Tab-Specific Migrations
- [x] Analyze admin.html structure and tabs
- [x] Create migration plan for each tab
- [x] Create admin_new.html base
- [x] Migrate tab 6: System Health (COMPLETE - uses iframe)
- [x] Migrate tab 5: Alert Management (COMPLETE - design system cards)
- [ ] Test tabs 5 & 6 in development
- [ ] Migrate tab 1: Upload Boundaries
- [ ] Migrate tab 2: Preview Data
- [ ] Migrate tab 7: User Management
- [ ] Migrate tab 3: Manage Boundaries
- [ ] Migrate tab 4: System Operations
- [ ] Migrate tab 8: Location Settings

## Priority 3: Settings Pages
- [ ] Migrate radio.html (1,064 lines)
- [ ] Apply form patterns
- [ ] Test all settings forms

## Priority 4: Final Integration
- [ ] Switch all pages to base_new.html
- [ ] Remove old template files
- [ ] Clean up unused CSS
- [ ] Final testing (light/dark mode)
- [ ] Mobile responsiveness testing
- [ ] Accessibility audit
- [ ] Performance testing

## Priority 5: Documentation
- [ ] Update UI improvements summary
- [ ] Create Phase 4 completion report
- [ ] Update roadmap
- [ ] Create deployment guide

## Notes
- Use form patterns from Phase 3
- Test each section before moving on
- Keep backups of all files
- Document any issues found