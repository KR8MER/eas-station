# 📇 EAS Station Documentation Index

> **Quick Search**: Use your browser's find function (Ctrl+F / Cmd+F) to search this index for keywords.

This comprehensive index catalogs all documentation across the EAS Station project. Each entry includes the topic, relevant keywords, and the document location.

> ℹ️ Keep the vendor-supplied **Digital Alert Systems DASDEC3 Version 5.1 Software User's Guide** at `docs/Version 5.1 Software_Users Guide_R1.0 5-31-23.pdf` (maintainer local copy, not version-controlled). Pair it with the `docs/QSG_DASDEC-G3_R5.1.docx` quick start and the `docs/D,GrobSystems,ADJ06182024A.pdf` project dossier when updating roadmap parity notes.

---

## 📚 Complete Documentation Catalog

### Core Project Documentation

| Topic | Keywords | Document | Lines |
|-------|----------|----------|-------|
| Project overview, quick start, architecture | readme, getting started, overview, architecture, docker | [README.md](../README.md) | 1,395 |
| Project mission, goals, technology stack | about, mission, vision, goals, stack, python | [reference/ABOUT.md](reference/ABOUT.md) | 73 |
| Theory of operation, system flow, SAME internals | architecture, pipeline, mermaid, same, history | [architecture/THEORY_OF_OPERATION.md](architecture/THEORY_OF_OPERATION.md) | 109 |
| Developer guidelines, code standards | agents, coding standards, security, patterns, testing | [development/AGENTS.md](development/AGENTS.md) | 549 |
| License information | mit, license, copyright | [LICENSE](../LICENSE) | 22 |

### Project Philosophy & Vision

| Topic | Keywords | Document | Lines |
|-------|----------|----------|-------|
| Raspberry Pi history and evolution | raspberry pi, history, eben upton, foundation, evolution, models | [raspberry-pi-history.md](raspberry-pi-history.md) | 450+ |
| Project philosophy and goals | philosophy, vision, goals, dasdec3, alternative, open source, democratization | [project-philosophy.md](project-philosophy.md) | 500+ |
| DASDEC3 feature comparison | dasdec3, comparison, features, cost, specifications, commercial | [dasdec3-comparison.md](dasdec3-comparison.md) | 600+ |
| DASDEC3 feature implementation roadmap | roadmap, features, implementation, timeline, phases, parity | [roadmap/dasdec3-feature-roadmap.md](roadmap/dasdec3-feature-roadmap.md) | 800+ |

### Operations & Maintenance

| Topic | Keywords | Document | Lines |
|-------|----------|----------|-------|
| Daily operations, dashboard, monitoring | help, operations, dashboard, monitoring, alerts, audio | [guides/HELP.md](guides/HELP.md) | 90 |
| Database connection troubleshooting | database, postgresql, connection, troubleshooting, fixes | [guides/DATABASE_CONSISTENCY_FIXES.md](guides/DATABASE_CONSISTENCY_FIXES.md) | 313 |
| Environment variable migration | env, environment, migration, configuration, upgrade | [guides/ENV_MIGRATION_GUIDE.md](guides/ENV_MIGRATION_GUIDE.md) | 163 |
| Automated upgrade process | upgrade, update, docker, automation, one-button | [guides/one_button_upgrade.md](guides/one_button_upgrade.md) | 48 |
| Version history and release notes | changelog, versions, releases, history, changes | [reference/CHANGELOG.md](reference/CHANGELOG.md) | 321 |

### Integration & Configuration

| Topic | Keywords | Document | Lines |
|-------|----------|----------|-------|
| IPAWS feed integration | ipaws, pub-sub, polling, feed, integration, cap, alerts | [guides/ipaws_feed_integration.md](guides/ipaws_feed_integration.md) | 82 |
| SDR USB passthrough for Docker | radio, sdr, usb, passthrough, docker, rtl-sdr, receiver | [guides/radio_usb_passthrough.md](guides/radio_usb_passthrough.md) | 45 |
| API endpoints reference | api, rest, endpoints, http, routes, webhooks | [README.md#api-endpoints](../README.md) | - |

### Development

| Topic | Keywords | Document | Lines |
|-------|----------|----------|-------|
| Code style and patterns | coding, standards, style, patterns, best practices | [development/AGENTS.md](development/AGENTS.md) | 549 |
| Security practices | security, sanitization, sql injection, xss, csrf | [development/AGENTS.md#security](development/AGENTS.md) | - |
| Testing guidelines | testing, pytest, manual testing, test coverage | [development/AGENTS.md#testing](development/AGENTS.md) | - |
| Git workflow and branch syncing | git, workflow, branches, sync, pull, push, merge | [development/git_workflow.md](development/git_workflow.md) | 30 |
| Contributing guidelines | contributing, contributions, pull requests, dco | [process/CONTRIBUTING.md](process/CONTRIBUTING.md) | 41 |
| Pull request template | pr, pull request, template, checklist | [process/PR_DESCRIPTION.md](process/PR_DESCRIPTION.md) | 140 |

### Legal & Policies

| Topic | Keywords | Document | Lines |
|-------|----------|----------|-------|
| Terms of use, disclaimers | terms, legal, disclaimers, acceptable use, liability | [policies/TERMS_OF_USE.md](policies/TERMS_OF_USE.md) | 45 |
| Privacy policy | privacy, data, collection, storage, security | [policies/PRIVACY_POLICY.md](policies/PRIVACY_POLICY.md) | 37 |

### Technical Reference

| Topic | Keywords | Document | Lines |
|-------|----------|----------|-------|
| Open source dependencies | dependencies, licenses, attribution, third-party | [reference/dependency_attribution.md](reference/dependency_attribution.md) | 46 |
| FCC regulations (EAS/SAME) | fcc, regulations, cfr, same, eas, compliance | [reference/CFR-2010-title47-vol1-sec11-31.xml](reference/CFR-2010-title47-vol1-sec11-31.xml) | - |
| Theory of operation & SAME protocol | architecture, signal chain, history, mermaid | [architecture/THEORY_OF_OPERATION.md](architecture/THEORY_OF_OPERATION.md) | 109 |
| M-Protocol specification (LED signs) | m-protocol, led, signs, alpha, protocol, specification | [M-Protocol.pdf](M-Protocol.pdf) | PDF |

### Roadmap & Planning

| Topic | Keywords | Document | Lines |
|-------|----------|----------|-------|
| Drop-in replacement roadmap | roadmap, features, requirements, planning, saratoga | [roadmap/master_todo.md](roadmap/master_todo.md) | 125 |
| EAS-specific feature checklist | eas, same, audio, broadcast, alerts, verification | [roadmap/eas_todo.md](roadmap/eas_todo.md) | 72 |
| DASDEC3 capability comparison | dasdec, commercial parity, cost, roadmap | [roadmap/DASDEC3_COMPARISON.md](roadmap/DASDEC3_COMPARISON.md) | 94 |
| DASDEC3 vendor manuals (reference) | vendor manual, quick start, grob systems | [Version 5.1 Software_Users Guide_R1.0 5-31-23.pdf](Version%205.1%20Software_Users%20Guide_R1.0%205-31-23.pdf), [QSG_DASDEC-G3_R5.1.docx](QSG_DASDEC-G3_R5.1.docx), [D,GrobSystems,ADJ06182024A.pdf](D%2CGrobSystems%2CADJ06182024A.pdf) | External |

---

## 🔍 Search by Topic

### A

- **About** → [reference/ABOUT.md](reference/ABOUT.md)
- **AI Agents (Development)** → [development/AGENTS.md](development/AGENTS.md)
- **Alerts (Monitoring)** → [guides/HELP.md](guides/HELP.md), [README.md](../README.md)
- **API Endpoints** → [README.md#api-endpoints](../README.md)
- **Architecture** → [architecture/THEORY_OF_OPERATION.md](architecture/THEORY_OF_OPERATION.md), [reference/ABOUT.md](reference/ABOUT.md), [README.md](../README.md)
- **Audio Generation** → [guides/HELP.md](guides/HELP.md), [roadmap/eas_todo.md](roadmap/eas_todo.md)
- **Attribution (Dependencies)** → [reference/dependency_attribution.md](reference/dependency_attribution.md)

### B

- **Broadcast Control** → [roadmap/eas_todo.md](roadmap/eas_todo.md)
- **Bugs** → [guides/DATABASE_CONSISTENCY_FIXES.md](guides/DATABASE_CONSISTENCY_FIXES.md)

### C

- **CAP (Common Alerting Protocol)** → [guides/ipaws_feed_integration.md](guides/ipaws_feed_integration.md), [README.md](../README.md)
- **Changelog** → [reference/CHANGELOG.md](reference/CHANGELOG.md)
- **Code Standards** → [development/AGENTS.md](development/AGENTS.md)
- **Configuration** → [guides/ENV_MIGRATION_GUIDE.md](guides/ENV_MIGRATION_GUIDE.md), [README.md](../README.md)
- **Contributing** → [process/CONTRIBUTING.md](process/CONTRIBUTING.md)
- **Copyright** → [LICENSE](../LICENSE)

### D

- **Dashboard** → [guides/HELP.md](guides/HELP.md)
- **Database** → [guides/DATABASE_CONSISTENCY_FIXES.md](guides/DATABASE_CONSISTENCY_FIXES.md)
- **DASDEC3** → [roadmap/DASDEC3_COMPARISON.md](roadmap/DASDEC3_COMPARISON.md), [Version 5.1 Software_Users Guide_R1.0 5-31-23.pdf](Version%205.1%20Software_Users%20Guide_R1.0%205-31-23.pdf), [QSG_DASDEC-G3_R5.1.docx](QSG_DASDEC-G3_R5.1.docx)
- **DCO (Developer Certificate of Origin)** → [process/CONTRIBUTING.md](process/CONTRIBUTING.md)
- **Dependencies** → [reference/dependency_attribution.md](reference/dependency_attribution.md)
- **Development** → [development/AGENTS.md](development/AGENTS.md)
- **Docker** → [README.md](../README.md), [guides/one_button_upgrade.md](guides/one_button_upgrade.md)

### E

- **EAS (Emergency Alert System)** → [roadmap/eas_todo.md](roadmap/eas_todo.md), [README.md](../README.md)
- **Environment Variables** → [guides/ENV_MIGRATION_GUIDE.md](guides/ENV_MIGRATION_GUIDE.md)

### F

- **FCC Regulations** → [reference/CFR-2010-title47-vol1-sec11-31.xml](reference/CFR-2010-title47-vol1-sec11-31.xml)
- **Features** → [roadmap/master_todo.md](roadmap/master_todo.md), [roadmap/eas_todo.md](roadmap/eas_todo.md)

### G

- **Getting Started** → [README.md#quick-start](../README.md)
- **Git Workflow** → [development/git_workflow.md](development/git_workflow.md)

### H

- **Hardware** → [guides/radio_usb_passthrough.md](guides/radio_usb_passthrough.md)
- **Help** → [guides/HELP.md](guides/HELP.md)

### I

- **Installation** → [README.md#quick-start](../README.md)
- **Integration** → [guides/ipaws_feed_integration.md](guides/ipaws_feed_integration.md)
- **IPAWS** → [guides/ipaws_feed_integration.md](guides/ipaws_feed_integration.md)

### L

- **LED Signs** → [M-Protocol.pdf](M-Protocol.pdf)
- **Legal** → [policies/TERMS_OF_USE.md](policies/TERMS_OF_USE.md)
- **License** → [LICENSE](../LICENSE), [reference/dependency_attribution.md](reference/dependency_attribution.md)

### M

- **Migration** → [guides/ENV_MIGRATION_GUIDE.md](guides/ENV_MIGRATION_GUIDE.md)
- **Mission** → [reference/ABOUT.md](reference/ABOUT.md)
- **Monitoring** → [guides/HELP.md](guides/HELP.md)
- **M-Protocol** → [M-Protocol.pdf](M-Protocol.pdf)

### O

- **Operations** → [guides/HELP.md](guides/HELP.md)

### P

- **Patterns (Code)** → [development/AGENTS.md](development/AGENTS.md)
- **PostgreSQL** → [guides/DATABASE_CONSISTENCY_FIXES.md](guides/DATABASE_CONSISTENCY_FIXES.md)
- **Privacy** → [policies/PRIVACY_POLICY.md](policies/PRIVACY_POLICY.md)
- **Pull Requests** → [process/PR_DESCRIPTION.md](process/PR_DESCRIPTION.md), [process/CONTRIBUTING.md](process/CONTRIBUTING.md)
- **Python** → [reference/ABOUT.md](reference/ABOUT.md), [development/AGENTS.md](development/AGENTS.md)

### Q

- **Quick Start** → [README.md#quick-start](../README.md)

### R

- **Radio (SDR)** → [guides/radio_usb_passthrough.md](guides/radio_usb_passthrough.md)
- **Releases** → [reference/CHANGELOG.md](reference/CHANGELOG.md)
- **REST API** → [README.md#api-endpoints](../README.md)
- **Roadmap** → [roadmap/master_todo.md](roadmap/master_todo.md), [roadmap/eas_todo.md](roadmap/eas_todo.md)

### S

- **SAME (Specific Area Message Encoding)** → [architecture/THEORY_OF_OPERATION.md](architecture/THEORY_OF_OPERATION.md), [roadmap/eas_todo.md](roadmap/eas_todo.md), [reference/CFR-2010-title47-vol1-sec11-31.xml](reference/CFR-2010-title47-vol1-sec11-31.xml)
- **SDR (Software Defined Radio)** → [guides/radio_usb_passthrough.md](guides/radio_usb_passthrough.md)
- **Security** → [development/AGENTS.md#security](development/AGENTS.md)
- **Setup** → [README.md#quick-start](../README.md)

### T

- **Technology Stack** → [reference/ABOUT.md](reference/ABOUT.md)
- **Terms of Use** → [policies/TERMS_OF_USE.md](policies/TERMS_OF_USE.md)
- **Testing** → [development/AGENTS.md#testing](development/AGENTS.md)
- **Troubleshooting** → [guides/DATABASE_CONSISTENCY_FIXES.md](guides/DATABASE_CONSISTENCY_FIXES.md), [guides/HELP.md](guides/HELP.md)

### U

- **Upgrade** → [guides/one_button_upgrade.md](guides/one_button_upgrade.md)
- **USB Passthrough** → [guides/radio_usb_passthrough.md](guides/radio_usb_passthrough.md)

### V

- **Version Control** → [development/git_workflow.md](development/git_workflow.md)
- **Versions** → [reference/CHANGELOG.md](reference/CHANGELOG.md)

### W

- **Workflow (Git)** → [development/git_workflow.md](development/git_workflow.md)
- **Workflow (Contribution)** → [process/CONTRIBUTING.md](process/CONTRIBUTING.md)

---

## 📁 Files by Category

### User-Facing Documentation
```
README.md                                    (Main entry point)
docs/README.md                               (Documentation hub)
docs/guides/HELP.md                          (Operations)
docs/reference/ABOUT.md                      (Project info)
docs/policies/TERMS_OF_USE.md                (Legal)
docs/policies/PRIVACY_POLICY.md              (Privacy)
```

### Developer Documentation
```
docs/development/AGENTS.md                   (Primary dev guide)
docs/development/git_workflow.md             (Git operations)
docs/process/CONTRIBUTING.md                 (How to contribute)
docs/process/PR_DESCRIPTION.md               (PR template)
```

### Configuration & Setup
```
README.md                                    (Quick start)
docs/guides/ENV_MIGRATION_GUIDE.md           (Environment vars)
docs/guides/DATABASE_CONSISTENCY_FIXES.md    (Database setup)
docs/guides/radio_usb_passthrough.md         (Hardware config)
docs/guides/ipaws_feed_integration.md        (Feed integration)
```

### Maintenance & Operations
```
docs/guides/HELP.md                          (Daily operations)
docs/guides/one_button_upgrade.md            (Upgrades)
docs/reference/CHANGELOG.md                  (Version history)
```

### Reference Materials
```
docs/reference/ABOUT.md                      (Project overview)
docs/reference/dependency_attribution.md     (Licenses)
docs/reference/CHANGELOG.md                  (Release notes)
docs/reference/CFR-2010-title47-vol1-sec11-31.xml  (FCC regs)
docs/M-Protocol.pdf                          (LED protocol)
```

### Planning & Roadmap
```
docs/roadmap/master_todo.md                  (Overall roadmap)
docs/roadmap/eas_todo.md                     (EAS features)
```

---

## 🌐 Web-Based Documentation Routes

| URL | Template File | Description |
|-----|---------------|-------------|
| `/about` | `templates/about.html` | Interactive About page with architecture diagrams |
| `/help` | `templates/help.html` | Comprehensive operations guide with examples |
| `/terms` | `templates/terms.html` | Terms of Use |
| `/privacy` | `templates/privacy.html` | Privacy Policy |
| `/static/docs/radio_usb_passthrough.html` | Static HTML | Radio configuration guide |

---

## 📊 Documentation Metrics

| Metric | Value |
|--------|-------|
| Total Markdown Files | 18 |
| Total Documentation Lines | 3,313+ |
| PDF Documents | 1 (M-Protocol) |
| XML Reference Documents | 1 (FCC CFR) |
| Web Templates | 4 (HTML) |
| Static HTML Guides | 1 |
| Documentation Directories | 6 |

---

## 💡 Pro Tips

- **Use Ctrl+F / Cmd+F** on this page to search for any keyword
- **Start with [docs/README.md](README.md)** for visual navigation
- **Bookmark frequently used guides** from the web interface (`/help`, `/about`)
- **Check [CHANGELOG.md](reference/CHANGELOG.md)** for recent changes
- **Read [AGENTS.md](development/AGENTS.md)** before contributing code

---

**Last Updated**: 2025-11-02
**Index Version**: 1.0.0
