# 🚨 CRITICAL LICENSE COMPLIANCE ISSUE 🚨

**Date Identified**: 2025-11-23
**Status**: ❌ **BLOCKS COMMERCIAL DISTRIBUTION**
**Severity**: **CRITICAL**

## Executive Summary

**EAS Station currently uses Highcharts**, a commercial JavaScript charting library that **REQUIRES a paid commercial license** for any commercial use, including selling the software.

This dependency **MUST be removed** before any commercial release or sale of EAS Station.

---

## The Problem

### Highcharts License Restriction

- **Library**: Highcharts v12.4.0
- **Free License**: Creative Commons Attribution-NonCommercial 3.0
- **Restriction**: ❌ **CANNOT be used for commercial purposes** (selling software, SaaS, etc.)
- **Commercial License Cost**: $540 - $10,000+ depending on scale

### Where Highcharts is Used

1. **Statistics Dashboard** (`templates/stats/_scripts.html`)
   - 12+ different chart types (pie, column, heatmap, gauge, spline, stock charts)
   - Core analytics feature heavily integrated throughout dashboard
   - ~1,543 lines of JavaScript code dependent on Highcharts API

2. **Alert Delivery Charts** (`static/js/charts/alert_delivery.js`)
   - Alert verification visualization
   - Delivery rate tracking charts
   - 113 lines of code using Highcharts

### Legal Risk

**Using Highcharts in a commercial product without a license constitutes:**
- ❌ Copyright infringement
- ❌ License violation
- ❌ Potential legal liability

---

## ✅ ACKNOWLEDGMENT

**WE ACKNOWLEDGE THIS CRITICAL ISSUE**

The EAS Station development team recognizes this license compliance blocker and commits to the following:

### Commitment

1. **NO COMMERCIAL DISTRIBUTION** until Highcharts is removed
2. **Active roadmap item** to replace Highcharts with permissively-licensed alternative
3. **Clear disclaimer** in all documentation that current version contains non-commercial dependencies
4. **Priority replacement** with Chart.js (MIT licensed) or Apache ECharts (Apache 2.0)

### Current Status

- ✅ Issue documented and acknowledged
- ✅ Added to project roadmap as high-priority task
- ✅ All stakeholders notified
- ⏳ Replacement implementation in progress
- ❌ NOT READY for commercial release

---

## Recommended Solution

### Option 1: Replace with Chart.js (RECOMMENDED) ✅

- **License**: MIT (fully permissive, allows commercial use)
- **Cost**: $0
- **Already in use**: Chart.js is already loaded in the application
- **Effort**: Moderate - requires rewriting chart implementations
- **Timeline**: 2-4 weeks for full migration

### Option 2: Replace with Apache ECharts

- **License**: Apache 2.0 (permissive, allows commercial use)
- **Cost**: $0
- **Features**: Very feature-rich, excellent for complex visualizations
- **Effort**: Moderate - similar API to Highcharts
- **Timeline**: 2-4 weeks for full migration

### Option 3: Purchase Highcharts Commercial License (NOT RECOMMENDED)

- **Cost**: $540+ per developer (recurring annual cost)
- **Pros**: Keep existing code
- **Cons**: Ongoing licensing costs, vendor lock-in

---

## Migration Roadmap

See **Section 11: Highcharts Removal & Chart.js Migration** in `docs/roadmap/master_todo.md` for detailed implementation plan.

### High-Level Steps

1. **Audit all Highcharts usage** (COMPLETE ✅)
   - Identified 2 primary files
   - Documented all chart types in use

2. **Design Chart.js equivalents** (PENDING)
   - Map Highcharts chart types to Chart.js equivalents
   - Design unified charting abstraction layer

3. **Implement replacements** (PENDING)
   - Replace statistics dashboard charts
   - Replace alert delivery charts
   - Ensure feature parity

4. **Test and validate** (PENDING)
   - Verify all charts render correctly
   - Validate data accuracy
   - Cross-browser testing

5. **Remove Highcharts** (PENDING)
   - Delete all Highcharts references
   - Remove CDN script loads
   - Final license audit

---

## Other Dependencies: ✅ ALL CLEAR

All other dependencies have been audited and are cleared for commercial use:

- **Python packages**: MIT, BSD-3-Clause, Apache-2.0
- **System packages**: Properly isolated (GPL components run as separate Docker services)
- **JavaScript libraries**: MIT, BSD (except Highcharts)
- **Infrastructure**: nginx (BSD), certbot (Apache-2.0)

---

## Distribution Guidelines

### ✅ SAFE FOR:

- Open-source distribution under AGPL v3
- Non-commercial evaluation and testing
- Academic and educational use
- Internal organizational use (non-commercial)

### ❌ NOT SAFE FOR:

- **Commercial sale of the software**
- **SaaS/hosted service offerings (commercial)**
- **Bundling with commercial products**
- **Any revenue-generating use**

---

## Contact & Questions

For questions about this compliance issue:

- **GitHub Issues**: https://github.com/KR8MER/eas-station/issues
- **Commercial Licensing**: sales@easstation.com
- **Author**: Timothy Kramer (KR8MER)

---

## Version History

- **2025-11-23**: Initial documentation of Highcharts license compliance issue
- **2025-11-23**: Added to project roadmap as Section 11 (high priority)
- **2025-11-23**: Committed to Chart.js migration before any commercial release

---

**⚠️ IMPORTANT: DO NOT DISTRIBUTE THIS SOFTWARE COMMERCIALLY UNTIL HIGHCHARTS IS REMOVED ⚠️**
