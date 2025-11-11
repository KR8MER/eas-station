# 📚 EAS Station Documentation

Welcome to the comprehensive documentation for **EAS Station** - an experimental emergency alert monitoring and broadcasting system for amateur radio operators.

> ⚠️ **IMPORTANT**: This software is in active development and intended for laboratory/experimental use only. Not for production emergency alerting.

## 🚀 Quick Navigation

### For Operators
| Document | Description |
|----------|-------------|
| [**Help & Operations Guide**](/docs/guides/HELP) | Daily operations, dashboard access, alert monitoring |
| [**Quick Start**](https://github.com/KR8MER/eas-station/blob/main/README.md#quick-start) | Get up and running in 5 minutes |
| [**Setup Instructions**](/docs/guides/SETUP_INSTRUCTIONS) | First-run wizard, environment validation |
| [**Portainer Deployment**](/docs/guides/PORTAINER_DEPLOYMENT) | Complete guide for deploying and maintaining with Portainer |
| [**Database Fixes**](/docs/guides/DATABASE_CONSISTENCY_FIXES) | Troubleshooting database connection issues |
| [**Environment Migration**](/docs/guides/ENV_MIGRATION_GUIDE) | Migrating .env configuration between versions |
| [**One-Button Upgrade**](/docs/guides/one_button_upgrade) | Automated upgrade workflow |
| [**Audio Monitoring**](/docs/audio/AUDIO_MONITORING) | Live stream viewer, waveform analysis, troubleshooting |

### For Integrators
| Document | Description |
|----------|-------------|
| [**IPAWS Feed Integration**](/docs/guides/ipaws_feed_integration) | Configure IPAWS/Pub-Sub polling |
| [**Radio USB Passthrough**](/docs/guides/radio_usb_passthrough) | SDR receiver configuration for Docker |
| [**API Reference**](https://github.com/KR8MER/eas-station/blob/main/README.md#-api-endpoints) | REST API documentation |

### For Developers
| Document | Description |
|----------|-------------|
| [**Developer Guidelines (AGENTS.md)**](/docs/development/AGENTS) | Code style, patterns, security practices, testing |
| [**Contributing Guide**](/docs/process/CONTRIBUTING) | How to contribute, DCO workflow |
| [**PR Description Template**](/docs/process/PR_DESCRIPTION) | Pull request checklist |
| [**Git Workflow**](/docs/development/git_workflow) | Syncing branches and development workflow |

### Project Information
| Document | Description |
|----------|-------------|
| [**About**](/docs/reference/ABOUT) | Project mission, architecture, technology stack |
| [**Changelog**](/docs/reference/CHANGELOG) | Complete version history and release notes |
| [**Feature Matrix**](/docs/reference/FEATURE_MATRIX) | Documentation coverage by feature |
| [**Roadmap**](/docs/roadmap/master_todo) | Feature planning and requirements |
| [**DASDEC3 Comparison**](/docs/roadmap/DASDEC3_COMPARISON) | Gap analysis vs. commercial encoder/decoder |
| [**DASDEC3 Manuals (Reference)**](https://github.com/KR8MER/eas-station/blob/main/docs/Version%205.1%20Software_Users%20Guide_R1.0%205-31-23.pdf) | Vendor manual, quick start, Grob Systems dossier |
| [**License Attribution**](/docs/reference/dependency_attribution) | Open-source dependencies and licenses |
| [**System Architecture**](/docs/architecture/SYSTEM_ARCHITECTURE) | Comprehensive flowcharts and component diagrams |
| [**Theory of Operation**](/docs/architecture/THEORY_OF_OPERATION) | End-to-end system flow and SAME protocol internals |

### Legal & Policies
| Document | Description |
|----------|-------------|
| [**Terms of Use**](/docs/policies/TERMS_OF_USE) | Legal disclaimers and acceptable use |
| [**Privacy Policy**](/docs/policies/PRIVACY_POLICY) | Data handling and privacy guidance |

---

## 📖 Documentation Structure

```
docs/
├── README.md                          ← You are here
├── INDEX.md                           ← Searchable index of all topics
│
├── guides/                            ← Operational guides and how-tos
│   ├── HELP.md                       ← Primary operations guide
│   ├── SETUP_INSTRUCTIONS.md         ← First-run walkthrough
│   ├── PORTAINER_DEPLOYMENT.md       ← Portainer deployment guide
│   ├── DATABASE_CONSISTENCY_FIXES.md
│   ├── ENV_MIGRATION_GUIDE.md
│   ├── ipaws_feed_integration.md
│   ├── one_button_upgrade.md
│   ├── radio_usb_passthrough.md
│   └── sdr_setup_guide.md
│
├── audio/                             ← Audio monitoring and verification
│   └── AUDIO_MONITORING.md           ← Live monitoring dashboard guide
│
├── development/                       ← Developer documentation
│   ├── AGENTS.md                     ← Primary developer guide (code standards)
│   └── git_workflow.md               ← Version control workflow
│
├── deployment/                        ← Deployment runbooks
│   ├── audio_hardware.md             ← Hardware wiring reference
│   ├── post_install.md               ← Post-installation checklist
│   └── portainer/
│       ├── README.md                 ← Portainer doc overview
│       ├── PORTAINER_QUICK_START.md  ← Five-minute stack deployment
│       ├── PORTAINER_DATABASE_SETUP.md
│       └── PORTAINER_NETWORK_SETUP.md
│
├── reference/                         ← Technical reference
│   ├── ABOUT.md                      ← Project overview
│   ├── CHANGELOG.md                  ← Version history
│   ├── FEATURE_MATRIX.md             ← Coverage by feature
│   ├── dependency_attribution.md     ← License compliance
│   └── CFR-2010-title47-vol1-sec11-31.xml  ← FCC regulations
│
├── architecture/                      ← System theory of operation and diagrams
│   ├── SYSTEM_ARCHITECTURE.md        ← Comprehensive architecture diagrams
│   └── THEORY_OF_OPERATION.md        ← Detailed pipeline and SAME overview
│
├── archive/                           ← Historical reference material
│   ├── README.md                     ← Archive usage guidelines
│   └── 2025/
│       └── …                         ← Bug reports, security analyses, changelogs
│
├── policies/                          ← Legal and governance
│   ├── TERMS_OF_USE.md
│   └── PRIVACY_POLICY.md
│
├── process/                           ← Contribution workflow
│   ├── CONTRIBUTING.md
│   └── PR_DESCRIPTION.md
│
└── roadmap/                           ← Feature planning
    ├── master_todo.md                ← Drop-in replacement roadmap
    ├── eas_todo.md                   ← EAS-specific features
    └── DASDEC3_COMPARISON.md         ← Gap analysis vs. DASDEC3 manual
```

---

## 🔍 Find What You Need

### By Task
- **Setting up EAS Station for the first time?** → [Quick Start Guide](https://github.com/KR8MER/eas-station/blob/main/README.md#quick-start)
- **Deploying with Portainer?** → [Portainer Deployment Guide](/docs/guides/PORTAINER_DEPLOYMENT)
- **Operating the dashboard?** → [Help & Operations Guide](/docs/guides/HELP)
- **Contributing code?** → [Developer Guidelines](/docs/development/AGENTS) + [Contributing](/docs/process/CONTRIBUTING)
- **Troubleshooting issues?** → [Database Fixes](/docs/guides/DATABASE_CONSISTENCY_FIXES) + [Help Guide](/docs/guides/HELP)
- **Integrating with IPAWS?** → [IPAWS Integration Guide](/docs/guides/ipaws_feed_integration)
- **Configuring SDR hardware?** → [Radio USB Passthrough](/docs/guides/radio_usb_passthrough)
- **Monitoring audio feeds?** → [Audio Monitoring](/docs/audio/AUDIO_MONITORING)
- **Understanding the architecture?** → [System Architecture](/docs/architecture/SYSTEM_ARCHITECTURE) + [Theory of Operation](/docs/architecture/THEORY_OF_OPERATION) + [About](/docs/reference/ABOUT)
- **Checking version history?** → [Changelog](/docs/reference/CHANGELOG)

### By Audience
- **👨‍💼 Emergency Managers**: Start with [About](/docs/reference/ABOUT) and [Terms of Use](/docs/policies/TERMS_OF_USE)
- **📻 Radio Operators**: [Help Guide](/docs/guides/HELP) → [IPAWS Integration](/docs/guides/ipaws_feed_integration)
- **🎧 Audio Engineers**: [Audio Monitoring](/docs/audio/AUDIO_MONITORING) → [Professional Audio Subsystem](/docs/PROFESSIONAL_AUDIO_SUBSYSTEM)
- **💻 Developers**: [AGENTS.md](/docs/development/AGENTS) → [Contributing](/docs/process/CONTRIBUTING)
- **🔧 System Administrators**: [Portainer Deployment](/docs/guides/PORTAINER_DEPLOYMENT) → [Environment Migration](/docs/guides/ENV_MIGRATION_GUIDE) → [Database Fixes](/docs/guides/DATABASE_CONSISTENCY_FIXES)

---

## 📊 Documentation Statistics

| Metric | Value |
|--------|-------|
| Total Documentation Files | 18+ markdown files |
| Total Lines of Documentation | 3,300+ lines |
| Last Updated | See [CHANGELOG.md](/docs/reference/CHANGELOG) |
| Primary Maintainer | [KR8MER](https://github.com/KR8MER) |

---

## 🌐 Web-Based Documentation

In addition to these markdown files, EAS Station provides **web-based documentation** accessible through the application interface:

- **Web UI**: http://localhost:5000 (or your configured port)
  - `/about` - Interactive About page with architecture diagrams
  - `/help` - Comprehensive help with code examples and screenshots
  - `/terms` - Terms of Use
  - `/privacy` - Privacy Policy

---

## 🆘 Getting Help

1. **Check the documentation**: Start with [HELP.md](/docs/guides/HELP) or [INDEX.md](/docs/INDEX)
2. **Review troubleshooting**: [Database Fixes](/docs/guides/DATABASE_CONSISTENCY_FIXES)
3. **Search the codebase**: Use the comprehensive [INDEX.md](/docs/INDEX)
4. **File an issue**: [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
5. **Review changelog**: Check if your issue is addressed in [CHANGELOG.md](/docs/reference/CHANGELOG)

---

## 📝 Contributing to Documentation

Documentation improvements are always welcome! Please:

1. Follow the [Contributing Guide](/docs/process/CONTRIBUTING)
2. Keep the [Developer Guidelines](/docs/development/AGENTS) in mind
3. Update this README if you add new documentation files
4. Use clear, concise language appropriate for your audience
5. Include code examples where applicable
6. Test all links before submitting PRs

---

## 📜 License

This documentation is part of the EAS Station project, licensed under the MIT License. See [LICENSE](../LICENSE) for details.

---

**Last Updated**: 2025-11-15
**Documentation Version**: Corresponds to EAS Station v2.1.x+
