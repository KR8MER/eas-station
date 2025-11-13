# 📚 EAS Station Documentation Index

Welcome to the complete documentation for **EAS Station** - an Emergency Alert System platform built for amateur radio operators and emergency communications professionals.

## 🚀 Quick Start

If you're new to EAS Station, start here:

| Document | Description | Audience |
|----------|-------------|----------|
| [🔧 Main README](https://github.com/KR8MER/eas-station/blob/main/README.md) | Installation and overview | Everyone |
| [⚡ 5-Minute Quick Start](guides/HELP.md#getting-started) | Get running immediately | New users |
| [🐳 Portainer Deployment](guides/PORTAINER_DEPLOYMENT.md) | Container-based setup | System admins |

## 📊 Visual Documentation

**NEW:** Professional diagrams and flowcharts for system understanding:

| Diagram | Description | Use Case |
|---------|-------------|----------|
| [📊 All Diagrams Index](DIAGRAMS.md) | Complete visual documentation index | Browse all diagrams |
| [🔄 Alert Processing Pipeline](DIAGRAMS.md#1-alert-processing-pipeline) | CAP ingestion workflow | Understanding alert flow |
| [📡 EAS Broadcast Workflow](DIAGRAMS.md#2-eas-broadcast-workflow) | SAME generation & transmission | Operator training |
| [📻 SDR Setup Flow](DIAGRAMS.md#3-sdr-setup-configuration-flow) | Radio receiver configuration | Hardware setup |
| [🔊 Audio Source Routing](DIAGRAMS.md#4-audio-source-routing-architecture) | Audio ingestion architecture | Audio troubleshooting |
| [🖥️ Hardware Deployment](DIAGRAMS.md#5-hardware-deployment-architecture) | Raspberry Pi reference config | Physical installation |

## 👥 User Documentation

### Daily Operations
| Document | Description |
|----------|-------------|
| [📋 Help & Operations Guide](guides/HELP.md) | Complete operator manual |
| [🎨 Frontend User Guide](frontend/USER_INTERFACE_GUIDE.md) | Web interface navigation and usage |
| [🎯 Alert Management](guides/HELP.md#managing-boundaries-and-alerts) | Creating and managing alerts |
| [📊 System Monitoring](guides/HELP.md#routine-operations) | Dashboard and health checks |
| [🔧 Troubleshooting](guides/HELP.md#troubleshooting) | Common issues and solutions |

### Configuration & Setup
| Document | Description |
|----------|-------------|
| [📡 SDR Setup Guide](guides/sdr_setup_guide.md) | Radio receiver configuration |
| [🌐 IPAWS Integration](guides/ipaws_feed_integration.md) | Federal alert source setup |
| [🔄 Environment Migration](guides/ENV_MIGRATION_GUIDE.md) | Moving between versions |
| [🗄️ Database Setup](guides/DATABASE_CONSISTENCY_FIXES.md) | PostgreSQL/PostGIS configuration |
| [🛠️ Setup Instructions](guides/SETUP_INSTRUCTIONS.md) | Initial wizard and environment checklist |

### Hardware Integration
| Document | Description |
|----------|-------------|
| [⚡ GPIO Relay Control](guides/HELP.md#managing-receivers) | Transmitter keying setup |
| [🔊 Audio Configuration](guides/HELP.md#audio-generation-errors) | Sound card and audio routing |
| [🎧 Professional Audio Subsystem](PROFESSIONAL_AUDIO_SUBSYSTEM.md) | **NEW:** 24/7 audio monitoring architecture |
| [🔗 Audio System Access Guide](AUDIO_SYSTEM_ACCESS_GUIDE.md) | **NEW:** Quick reference for audio features |
| [🎧 Audio Monitoring Dashboard](audio/AUDIO_MONITORING.md) | Live stream viewer and troubleshooting |
| [💡 LED Sign Integration](guides/HELP.md#led-sign-not-responding) | Alpha Protocol signage |
| [📻 Radio Management](guides/radio_usb_passthrough.md) | USB radio devices |

### Web Interface & Frontend
| Document | Description |
|----------|-------------|
| [🎨 UI Components Library](frontend/COMPONENT_LIBRARY.md) | Complete component reference |
| [📱 Responsive Design Guide](frontend/RESPONSIVE_DESIGN.md) | Mobile-first design principles |
| [🎨 Theming & Customization](frontend/THEMING_CUSTOMIZATION.md) | Theme system and branding |
| [🚀 JavaScript API](frontend/JAVASCRIPT_API.md) | Frontend API documentation |

## 🛠️ Developer Documentation

### Getting Started
| Document | Description |
|----------|-------------|
| [🏗️ Architecture Overview](architecture/THEORY_OF_OPERATION.md) | System design and components |
| [💻 Development Setup](development/AGENTS.md) | Local development environment |
| [🎨 Frontend Documentation](frontend/FRONTEND_INDEX.md) | Complete UI and frontend guide |
| [🔧 API Reference](https://github.com/KR8MER/eas-station/blob/main/README.md#-api-endpoints) | REST API documentation |
| [🗺️ Project Structure](development/AGENTS.md) | Code organization guide |

### Contributing
| Document | Description |
|----------|-------------|
| [📋 Contributing Guide](process/CONTRIBUTING.md) | How to contribute code |
| [✅ Pull Request Process](process/PR_DESCRIPTION.md) | PR guidelines and templates |
| [🐛 Issue Reporting](process/CONTRIBUTING.md#how-to-contribute) | Bug report guidelines |
| [📝 Code Standards](development/AGENTS.md) | Style and quality standards |
| [🎨 Frontend Development](frontend/FRONTEND_INDEX.md) | UI development guidelines |

## 📈 Project Information

### Planning & Roadmap
| Document | Description |
|----------|-------------|
| [🗺️ Project Roadmap](roadmap/master_todo.md) | Current development priorities |
| [🎯 Feature Timeline](roadmap/dasdec3-feature-roadmap.md) | Release schedule and milestones |
| [🏆 DASDEC3 Comparison](dasdec3-comparison.md) | Hardware replacement analysis |
| [📋 Project Philosophy](project-philosophy.md) | Goals and principles |

### Reference Materials
| Document | Description |
|----------|-------------|
| [📖 About EAS Station](reference/ABOUT.md) | Project background and goals |
| [📄 Changelog](/docs/reference/CHANGELOG) | Version history and changes |
| [🧭 Feature Matrix](/docs/reference/FEATURE_MATRIX) | Documentation coverage by feature |
| [🎵 Audio System Changelog (2025-11-07)](/docs/CHANGELOG_2025-11-07) | **NEW:** Professional audio subsystem build log |
| [📊 Documentation Audit](/docs/documentation_audit) | Documentation status and maintenance tracking |
| [🗃️ Documentation Archive](/docs/archive/README) | Historical bug reports & security analyses |
| [🔐 Security Policy](development/AGENTS.md) | Security considerations |
| [📜 License](https://github.com/KR8MER/eas-station/blob/main/LICENSE) | MIT License terms |

## 🏢 Operational Documentation

### Deployment & Maintenance
| Document | Description |
|----------|-------------|
| [🐳 Docker Deployment](https://github.com/KR8MER/eas-station/blob/main/README.md#-quick-start) | Container setup and management |
| [🚀 Portainer Quick Start](/docs/deployment/portainer/PORTAINER_QUICK_START) | Five-minute stack deployment |
| [🗄️ Portainer Database Setup](/docs/deployment/portainer/PORTAINER_DATABASE_SETUP) | External database configuration |
| [🌐 Portainer Network Setup](/docs/deployment/portainer/PORTAINER_NETWORK_SETUP) | Reverse proxy and DNS guidance |
| [🔄 One-Button Upgrade](/docs/guides/one_button_upgrade) | Automated update process |
| [🧰 Post Install Checklist](/docs/deployment/post_install) | Finalize services and accounts |
| [📊 Performance Tuning](audio.md#performance-optimization) | Optimization guidelines |
| [🔍 Monitoring & Logging](guides/HELP.md#troubleshooting) | System observability |

### Compliance & Standards
| Document | Description |
|----------|-------------|
| [📡 FCC Part 11 Compliance](reference/CFR-2010-title47-vol1-sec11-31.xml) | Regulatory requirements |
| [🌐 CAP Protocol Guide](/docs/guides/ipaws_feed_integration) | Common Alert Protocol implementation |
| [📻 SAME Encoding Standards](/docs/architecture/THEORY_OF_OPERATION) | Standard Alert Messaging Protocol |
| [🗺️ Geographic Standards](guides/HELP.md#managing-boundaries-and-alerts) | Location-based filtering rules |

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
- **👨‍💻 Operators**: See [Help & Operations Guide](/docs/guides/HELP)
- **🔧 System Admins**: Check [Deployment Guides](https://github.com/KR8MER/eas-station/blob/main/README.md#-quick-start)
- **💻 Developers**: Review [Development Setup](/docs/development/AGENTS)

### By Task
- **🚀 Installation**: [Installation Guides](#quick-start)
- **⚙️ Configuration**: [Configuration & Setup](#configuration-setup)
- **🔧 Troubleshooting**: [Help & Operations](guides/HELP.md#troubleshooting)
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
- **Check [CHANGELOG](/docs/reference/CHANGELOG)** for recent changes
- **Read [Development Guide](/docs/development/AGENTS)** before contributing code

---

**Last Updated**: 2025-11-08
**Version**: 2.1
**For questions or contributions, see the [Contributing Guide](/docs/process/CONTRIBUTING)**