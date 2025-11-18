# 📚 EAS Station Documentation Index

Welcome to the complete documentation for **EAS Station** - an Emergency Alert System platform built for amateur radio operators and emergency communications professionals.

## 🚀 Quick Start

If you're new to EAS Station, start here:

| Document | Description | Audience |
|----------|-------------|----------|
| [🔧 Main README](https://github.com/KR8MER/eas-station/blob/main/README.md) | Installation and overview | Everyone |
| [⚡ 5-Minute Quick Start](guides/HELP#getting-started) | Get running immediately | New users |
| [🐳 Portainer Deployment](guides/PORTAINER_DEPLOYMENT) | Container-based setup | System admins |

## 📊 Visual Documentation

**NEW:** Professional diagrams and flowcharts for system understanding:

| Diagram | Description | Use Case |
|---------|-------------|----------|
| [📊 All Diagrams Index](DIAGRAMS) | Complete visual documentation index | Browse all diagrams |
| [🔄 Alert Processing Pipeline](DIAGRAMS#1-alert-processing-pipeline) | CAP ingestion workflow | Understanding alert flow |
| [📡 EAS Broadcast Workflow](DIAGRAMS#2-eas-broadcast-workflow) | SAME generation & transmission | Operator training |
| [📻 SDR Setup Flow](DIAGRAMS#3-sdr-setup-configuration-flow) | Radio receiver configuration | Hardware setup |
| [🔊 Audio Source Routing](DIAGRAMS#4-audio-source-routing-architecture) | Audio ingestion architecture | Audio troubleshooting |
| [🖥️ Hardware Deployment](DIAGRAMS#5-hardware-deployment-architecture) | Raspberry Pi reference config | Physical installation |

## 👥 User Documentation

### Daily Operations
| Document | Description |
|----------|-------------|
| [📋 Help & Operations Guide](guides/HELP) | Complete operator manual |
| [🎨 Frontend User Guide](frontend/USER_INTERFACE_GUIDE) | Web interface navigation and usage |
| [🎯 Alert Management](guides/HELP#managing-boundaries-and-alerts) | Creating and managing alerts |
| [📊 System Monitoring](guides/HELP#routine-operations) | Dashboard and health checks |
| [🔧 Troubleshooting](guides/HELP#troubleshooting) | Common issues and solutions |

### Configuration & Setup
| Document | Description |
|----------|-------------|
| [📡 SDR Setup Guide](guides/sdr_setup_guide) | Radio receiver configuration |
| [🌐 IPAWS Integration](guides/ipaws_feed_integration) | Federal alert source setup |
| [🔄 Environment Migration](guides/ENV_MIGRATION_GUIDE) | Moving between versions |
| [🗄️ Database Setup](guides/DATABASE_CONSISTENCY_FIXES) | PostgreSQL/PostGIS configuration |
| [🛠️ Setup Instructions](guides/SETUP_INSTRUCTIONS) | Initial wizard and environment checklist |

### Hardware Integration
| Document | Description |
|----------|-------------|
| [⚡ GPIO Relay Control](guides/HELP#managing-receivers) | Transmitter keying setup |
| [🔊 Audio Configuration](guides/HELP#audio-generation-errors) | Sound card and audio routing |
| [🎧 Professional Audio Subsystem](PROFESSIONAL_AUDIO_SUBSYSTEM) | **NEW:** 24/7 audio monitoring architecture |
| [🔗 Audio System Access Guide](AUDIO_SYSTEM_ACCESS_GUIDE) | **NEW:** Quick reference for audio features |
| [🎧 Audio Monitoring Dashboard](audio/AUDIO_MONITORING) | Live stream viewer and troubleshooting |
| [💡 LED Sign Integration](guides/HELP#led-sign-not-responding) | Alpha Protocol signage |
| [🔌 Serial Bridge Setup](guides/SERIAL_ETHERNET_BRIDGE_SETUP) | Configure Lantronix and Linovision adapters |
| [📻 Radio Management](guides/radio_usb_passthrough) | USB radio devices |

### Web Interface & Frontend
| Document | Description |
|----------|-------------|
| [🎨 UI Components Library](frontend/COMPONENT_LIBRARY) | Complete component reference |
| [📱 Responsive Design Guide](frontend/RESPONSIVE_DESIGN) | Mobile-first design principles |
| [🎨 Theming & Customization](frontend/THEMING_CUSTOMIZATION) | Theme system and branding |
| [🚀 JavaScript API](frontend/JAVASCRIPT_API) | Frontend API documentation |

## 🛠️ Developer Documentation

### Getting Started
| Document | Description |
|----------|-------------|
| [🏗️ Architecture Overview](architecture/THEORY_OF_OPERATION) | System design and components |
| [💻 Development Setup](development/AGENTS) | Local development environment |
| [🎨 Frontend Documentation](frontend/FRONTEND_INDEX) | Complete UI and frontend guide |
| [🔧 API Reference](https://github.com/KR8MER/eas-station/blob/main/README.md#-api-endpoints) | REST API documentation |
| [🗺️ Project Structure](development/AGENTS) | Code organization guide |

### Contributing
| Document | Description |
|----------|-------------|
| [📋 Contributing Guide](process/CONTRIBUTING) | How to contribute code |
| [✅ Pull Request Process](process/PR_DESCRIPTION) | PR guidelines and templates |
| [🐛 Issue Reporting](process/CONTRIBUTING#how-to-contribute) | Bug report guidelines |
| [📝 Code Standards](development/AGENTS) | Style and quality standards |
| [🎨 Frontend Development](frontend/FRONTEND_INDEX) | UI development guidelines |

### Historical Development References (Archive)
Legacy files that still contain useful background material are now located under `docs/development/archive/`:

| Document | Why it matters |
|----------|----------------|
| [🤖 AI Assistant Guide](development/archive/CLAUDE.md) | Workflow guardrails for automation/AI contributors |
| [🧱 Frontend Architecture](development/archive/FRONTEND_ARCHITECTURE.md) | Deep dive into the display system and Flask UI layers |
| [🖥️ Display Quick Reference](development/archive/DISPLAY_QUICK_REFERENCE.md) | One-page cheat sheet for OLED/LED display modes |
| [⚙️ Config Persistence](development/archive/CONFIG_PERSISTENCE.md) | Raspberry Pi volume/backups for persistent installs |
| [🚀 Pi Quick Start](development/archive/QUICKSTART_PI.md) | Step-by-step OLED + GPIO bring-up on Raspberry Pi |
| [🔌 OLED/GPIO Troubleshooting](development/archive/OLED_GPIO_TROUBLESHOOTING.md) | Direct fixes when Docker cannot access GPIO hardware |
| [🖼️ OLED Sample Screens](development/archive/OLED_SAMPLE_SCREENS.md) | Reference layouts for 128x64 modules |
| [✨ Feature Enhancement Summary](development/archive/FEATURE_ENHANCEMENT_SUMMARY.md) | Context for major UI/UX upgrades |
| [🛠️ Fix + Proof Pack](development/archive/FIX_SUMMARY.md) | Bug write-up with links to smoking-gun & visual proof artifacts |

## 📈 Project Information

### Planning & Roadmap
| Document | Description |
|----------|-------------|
| [🗺️ Project Roadmap](roadmap/master_todo) | Current development priorities |
| [🎯 Feature Timeline](roadmap/dasdec3-feature-roadmap) | Release schedule and milestones |
| [🏆 DASDEC3 Comparison](dasdec3-comparison) | Hardware replacement analysis |
| [📋 Project Philosophy](project-philosophy) | Goals and principles |

### Reference Materials
| Document | Description |
|----------|-------------|
| [📖 About EAS Station](reference/ABOUT) | Project background and goals |
| [📄 Changelog](reference/CHANGELOG) | Version history and changes |
| [🧭 Feature Matrix](reference/FEATURE_MATRIX) | Documentation coverage by feature |
| [🎵 Audio System Changelog (2025-11-07)](CHANGELOG_2025-11-07) | **NEW:** Professional audio subsystem build log |
| [📊 Documentation Audit](documentation_audit) | Documentation status and maintenance tracking |
| [🗃️ Documentation Archive](archive/README) | Historical bug reports & security analyses |
| [🔐 Security Policy](development/AGENTS) | Security considerations |
| [📜 License](https://github.com/KR8MER/eas-station/blob/main/LICENSE) | MIT License terms |

## 🏢 Operational Documentation

### Deployment & Maintenance
| Document | Description |
|----------|-------------|
| [🐳 Docker Deployment](https://github.com/KR8MER/eas-station/blob/main/README.md#-quick-start) | Container setup and management |
| [🚀 Portainer Quick Start](deployment/portainer/PORTAINER_QUICK_START) | Five-minute stack deployment |
| [🗄️ Portainer Database Setup](deployment/portainer/PORTAINER_DATABASE_SETUP) | External database configuration |
| [🌐 Portainer Network Setup](deployment/portainer/PORTAINER_NETWORK_SETUP) | Reverse proxy and DNS guidance |
| [🔄 One-Button Upgrade](guides/one_button_upgrade) | Automated update process |
| [🧰 Post Install Checklist](deployment/post_install) | Finalize services and accounts |
| [📊 Performance Tuning](audio#performance-optimization) | Optimization guidelines |
| [🔍 Monitoring & Logging](guides/HELP#troubleshooting) | System observability |

### Compliance & Standards
| Document | Description |
|----------|-------------|
| [📡 FCC Part 11 Compliance](reference/CFR-2010-title47-vol1-sec11-31.xml) | Regulatory requirements |
| [🌐 CAP Protocol Guide](guides/ipaws_feed_integration) | Common Alert Protocol implementation |
| [📻 SAME Encoding Standards](architecture/THEORY_OF_OPERATION) | Standard Alert Messaging Protocol |
| [🗺️ Geographic Standards](guides/HELP#managing-boundaries-and-alerts) | Location-based filtering rules |

## 📁 File Organization

```
docs/
├── guides/          # User guides and tutorials
├── development/     # Developer documentation
├── architecture/    # System architecture docs
├── roadmap/         # Project planning and milestones
├── reference/       # Reference materials
├── policies/        # Project policies and governance
├── process/         # Development processes
└── development/archive/  # Historical development artifacts
```

## 🔍 Finding Information

### By User Type
- **🎯 New Users**: Start with [Quick Start](https://github.com/KR8MER/eas-station/blob/main/README.md#-quick-start)
- **👨‍💻 Operators**: See [Help & Operations Guide](guides/HELP)
- **🔧 System Admins**: Check [Deployment Guides](https://github.com/KR8MER/eas-station/blob/main/README.md#-quick-start)
- **💻 Developers**: Review [Development Setup](development/AGENTS)

### By Task
- **🚀 Installation**: [Installation Guides](#quick-start)
- **⚙️ Configuration**: [Configuration & Setup](#configuration-setup)
- **🔧 Troubleshooting**: [Help & Operations](guides/HELP#troubleshooting)
- **🛠️ Development**: [Developer Documentation](#developer-documentation)
- **📈 Project Info**: [Project Information](#project-information)

## 🆘 Getting Help

1. **Check Documentation**: Start with the relevant guide above
2. **Search Issues**: [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
3. **Review Logs**: Check application logs with `docker compose logs -f`
4. **Community Support**: [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)

## 📝 Documentation Status

| Section | Status | Last Updated |
|---------|--------|--------------|
| User Guides | ✅ Complete | 2025-01-28 |
| Developer Docs | ✅ Complete | 2025-01-28 |
| API Reference | ✅ Complete | 2025-01-28 |
| Compliance Docs | ✅ Complete | 2025-01-28 |
| Architecture | ✅ Complete | 2025-01-28 |
| Audio Subsystem | ✅ Complete | 2025-11-07 |
| Documentation Audit | ✅ Updated | 2025-11-08 |

## 📊 Documentation Metrics

| Metric | Value |
|--------|-------|
| Total Markdown Files | 43+ |
| Total Documentation Lines | 9,500+ |
| PDF Documents | 3 (vendor references) |
| XML Reference Documents | 1 (FCC regulations) |
| Documentation Directories | 8 |

## 🧭 Navigation Tips

- **Use Ctrl+F / Cmd+F** on this page to search for any keyword
- **Start with [Main README](https://github.com/KR8MER/eas-station/blob/main/README.md)** for visual navigation
- **Bookmark frequently used guides** from the web interface
- **Check [CHANGELOG](reference/CHANGELOG)** for recent changes
- **Read [Development Guide](development/AGENTS)** before contributing code

---

**Last Updated**: 2025-11-08
**Version**: 2.1
**For questions or contributions, see the [Contributing Guide](process/CONTRIBUTING)**