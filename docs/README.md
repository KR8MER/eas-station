# 📚 EAS Station Documentation

Welcome to the comprehensive documentation for **EAS Station** - an experimental emergency alert monitoring and broadcasting system for amateur radio operators.

> ⚠️ **IMPORTANT**: This software is in active development and intended for laboratory/experimental use only. Not for production emergency alerting.

## 🚀 Quick Navigation

### For Operators
| Document | Description |
|----------|-------------|
| [**Help & Operations Guide**](guides/HELP.md) | Daily operations, dashboard access, alert monitoring |
| [**Quick Start**](https://github.com/KR8MER/eas-station/blob/main/README.md#quick-start) | Get up and running in 5 minutes |
| [**Setup Instructions**](guides/SETUP_INSTRUCTIONS.md) | First-run wizard, environment validation |
| [**Portainer Deployment**](guides/PORTAINER_DEPLOYMENT.md) | Complete guide for deploying and maintaining with Portainer |
| [**Database Fixes**](guides/DATABASE_CONSISTENCY_FIXES.md) | Troubleshooting database connection issues |
| [**Environment Migration**](guides/ENV_MIGRATION_GUIDE.md) | Migrating .env configuration between versions |
| [**One-Button Upgrade**](guides/one_button_upgrade.md) | Automated upgrade workflow |
| [**Audio Monitoring**](audio/AUDIO_MONITORING.md) | Live stream viewer, waveform analysis, troubleshooting |

### For Integrators
| Document | Description |
|----------|-------------|
| [**IPAWS Feed Integration**](guides/ipaws_feed_integration.md) | Configure IPAWS/Pub-Sub polling |
| [**Radio USB Passthrough**](guides/radio_usb_passthrough.md) | SDR receiver configuration for Docker |
| [**API Reference**](https://github.com/KR8MER/eas-station/blob/main/README.md#-api-endpoints) | REST API documentation |

### For Developers
| Document | Description |
|----------|-------------|
| [**Developer Guidelines (AGENTS.md)**](development/AGENTS.md) | Code style, patterns, security practices, testing |
| [**Contributing Guide**](process/CONTRIBUTING.md) | How to contribute, DCO workflow |
| [**PR Description Template**](process/PR_DESCRIPTION.md) | Pull request checklist |
| [**Git Workflow**](development/git_workflow.md) | Syncing branches and development workflow |

### Project Information
| Document | Description |
|----------|-------------|
| [**About**](reference/ABOUT.md) | Project mission, architecture, technology stack |
| [**Changelog**](reference/CHANGELOG.md) | Complete version history and release notes |
| [**Feature Matrix**](reference/FEATURE_MATRIX.md) | Documentation coverage by feature |
| [**Roadmap**](roadmap/) | Feature planning and requirements |
| [**DASDEC3 Comparison**](roadmap/DASDEC3_COMPARISON.md) | Gap analysis vs. commercial encoder/decoder |
| [**DASDEC3 Manuals (Reference)**](Version%205.1%20Software_Users%20Guide_R1.0%205-31-23.pdf) | Vendor manual, quick start, Grob Systems dossier |
| [**License Attribution**](reference/dependency_attribution.md) | Open-source dependencies and licenses |
| [**System Architecture**](architecture/SYSTEM_ARCHITECTURE.md) | Comprehensive flowcharts and component diagrams |
| [**Theory of Operation**](architecture/THEORY_OF_OPERATION.md) | End-to-end system flow and SAME protocol internals |

### Legal & Policies
| Document | Description |
|----------|-------------|
| [**Terms of Use**](policies/TERMS_OF_USE.md) | Legal disclaimers and acceptable use |
| [**Privacy Policy**](policies/PRIVACY_POLICY.md) | Data handling and privacy guidance |

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
- **Deploying with Portainer?** → [Portainer Deployment Guide](guides/PORTAINER_DEPLOYMENT.md)
- **Operating the dashboard?** → [Help & Operations Guide](guides/HELP.md)
- **Contributing code?** → [Developer Guidelines](development/AGENTS.md) + [Contributing](process/CONTRIBUTING.md)
- **Troubleshooting issues?** → [Database Fixes](guides/DATABASE_CONSISTENCY_FIXES.md) + [Help Guide](guides/HELP.md)
- **Integrating with IPAWS?** → [IPAWS Integration Guide](guides/ipaws_feed_integration.md)
- **Configuring SDR hardware?** → [Radio USB Passthrough](guides/radio_usb_passthrough.md)
- **Monitoring audio feeds?** → [Audio Monitoring](audio/AUDIO_MONITORING.md)
- **Understanding the architecture?** → [System Architecture](architecture/SYSTEM_ARCHITECTURE.md) + [Theory of Operation](architecture/THEORY_OF_OPERATION.md) + [About](reference/ABOUT.md)
- **Checking version history?** → [Changelog](reference/CHANGELOG.md)

### By Audience
- **👨‍💼 Emergency Managers**: Start with [About](reference/ABOUT.md) and [Terms of Use](policies/TERMS_OF_USE.md)
- **📻 Radio Operators**: [Help Guide](guides/HELP.md) → [IPAWS Integration](guides/ipaws_feed_integration.md)
- **🎧 Audio Engineers**: [Audio Monitoring](audio/AUDIO_MONITORING.md) → [Professional Audio Subsystem](PROFESSIONAL_AUDIO_SUBSYSTEM.md)
- **💻 Developers**: [AGENTS.md](development/AGENTS.md) → [Contributing](process/CONTRIBUTING.md)
- **🔧 System Administrators**: [Portainer Deployment](guides/PORTAINER_DEPLOYMENT.md) → [Environment Migration](guides/ENV_MIGRATION_GUIDE.md) → [Database Fixes](guides/DATABASE_CONSISTENCY_FIXES.md)

---

## 📊 Documentation Statistics

| Metric | Value |
|--------|-------|
| Total Documentation Files | 18+ markdown files |
| Total Lines of Documentation | 3,300+ lines |
| Last Updated | See [CHANGELOG.md](reference/CHANGELOG.md) |
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

1. **Check the documentation**: Start with [HELP.md](guides/HELP.md) or [INDEX.md](INDEX.md)
2. **Review troubleshooting**: [Database Fixes](guides/DATABASE_CONSISTENCY_FIXES.md)
3. **Search the codebase**: Use the comprehensive [INDEX.md](INDEX.md)
4. **File an issue**: [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
5. **Review changelog**: Check if your issue is addressed in [CHANGELOG.md](reference/CHANGELOG.md)

---

## 📝 Contributing to Documentation

Documentation improvements are always welcome! Please:

1. Follow the [Contributing Guide](process/CONTRIBUTING.md)
2. Keep the [Developer Guidelines](development/AGENTS.md) in mind
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
