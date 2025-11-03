# 📚 EAS Station Documentation Index

Welcome to the complete documentation for **EAS Station** - an Emergency Alert System platform built for amateur radio operators and emergency communications professionals.

## 🚀 Quick Start

If you're new to EAS Station, start here:

| Document | Description | Audience |
|----------|-------------|----------|
| [🔧 Main README](../README.md) | Installation and overview | Everyone |
| [⚡ 5-Minute Quick Start](guides/HELP.md#getting-started) | Get running immediately | New users |
| [🐳 Portainer Deployment](guides/PORTAINER_DEPLOYMENT.md) | Container-based setup | System admins |

## 👥 User Documentation

### Daily Operations
| Document | Description |
|----------|-------------|
| [📋 Help & Operations Guide](guides/HELP.md) | Complete operator manual |
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

### Hardware Integration
| Document | Description |
|----------|-------------|
| [⚡ GPIO Relay Control](guides/HELP.md#managing-receivers) | Transmitter keying setup |
| [🔊 Audio Configuration](guides/HELP.md#audio-generation-errors) | Sound card and audio routing |
| [💡 LED Sign Integration](guides/HELP.md#led-sign-not-responding) | Alpha Protocol signage |
| [📻 Radio Management](guides/radio_usb_passthrough.md) | USB radio devices |

## 🛠️ Developer Documentation

### Getting Started
| Document | Description |
|----------|-------------|
| [🏗️ Architecture Overview](architecture/THEORY_OF_OPERATION.md) | System design and components |
| [💻 Development Setup](development/AGENTS.md) | Local development environment |
| [🔧 API Reference](../README.md#api-endpoints) | REST API documentation |
| [🗺️ Project Structure](development/AGENTS.md#project-structure) | Code organization guide |

### Contributing
| Document | Description |
|----------|-------------|
| [📋 Contributing Guide](process/CONTRIBUTING.md) | How to contribute code |
| [✅ Pull Request Process](process/PR_DESCRIPTION.md) | PR guidelines and templates |
| [🐛 Issue Reporting](process/CONTRIBUTING.md#issues) | Bug report guidelines |
| [📝 Code Standards](development/AGENTS.md#coding-standards) | Style and quality standards |

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
| [📄 Changelog](reference/CHANGELOG.md) | Version history and changes |
| [🔐 Security Policy](development/AGENTS.md#security) | Security considerations |
| [📜 License](../LICENSE) | MIT License terms |

## 🏢 Operational Documentation

### Deployment & Maintenance
| Document | Description |
|----------|-------------|
| [🐳 Docker Deployment](../README.md#-quick-start) | Container setup and management |
| [🔄 One-Button Upgrade](guides/one_button_upgrade.md) | Automated update process |
| [📊 Performance Tuning](guides/HELP.md#optimization) | Optimization guidelines |
| [🔍 Monitoring & Logging](guides/HELP.md#monitoring) | System observability |

### Compliance & Standards
| Document | Description |
|----------|-------------|
| [📡 FCC Part 11 Compliance](reference/CFR-2010-title47-vol1-sec11-31.xml) | Regulatory requirements |
| [🌐 CAP Protocol Guide](guides/ipaws_feed_integration.md) | Common Alert Protocol implementation |
| [📻 SAME Encoding Standards](architecture/THEORY_OF_OPERATION.md) | Standard Alert Messaging Protocol |
| [🗺️ Geographic Standards](guides/HELP.md#geographic-filtering) | Location-based filtering rules |

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
- **🎯 New Users**: Start with [Quick Start](../README.md#-quick-start)
- **👨‍💻 Operators**: See [Help & Operations Guide](guides/HELP.md)
- **🔧 System Admins**: Check [Deployment Guides](../README.md#-quick-start)
- **💻 Developers**: Review [Development Setup](development/AGENTS.md)

### By Task
- **🚀 Installation**: [Installation Guides](#-quick-start)
- **⚙️ Configuration**: [Configuration & Setup](#-configuration--setup)
- **🔧 Troubleshooting**: [Help & Operations](guides/HELP.md#troubleshooting)
- **🛠️ Development**: [Developer Documentation](#-developer-documentation)
- **📈 Project Info**: [Project Information](#-project-information)

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

## 📊 Documentation Metrics

| Metric | Value |
|--------|-------|
| Total Markdown Files | 40+ |
| Total Documentation Lines | 8,000+ |
| PDF Documents | 3 (vendor references) |
| XML Reference Documents | 1 (FCC regulations) |
| Documentation Directories | 8 |

## 🧭 Navigation Tips

- **Use Ctrl+F / Cmd+F** on this page to search for any keyword
- **Start with [Main README](../README.md)** for visual navigation
- **Bookmark frequently used guides** from the web interface
- **Check [CHANGELOG](reference/CHANGELOG.md)** for recent changes
- **Read [Development Guide](development/AGENTS.md)** before contributing code

---

**Last Updated**: 2025-01-28  
**Version**: 2.0  
**For questions or contributions, see the [Contributing Guide](process/CONTRIBUTING.md)**