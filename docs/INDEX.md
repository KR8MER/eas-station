# 📚 EAS Station Documentation Index

Welcome to the complete documentation for **EAS Station** - an Emergency Alert System platform built for amateur radio operators and emergency communications professionals.

## 🚀 Quick Start

If you're new to EAS Station, start here:

| Document | Description | Audience |
|----------|-------------|----------|
| [🔧 Main README](https://github.com/KR8MER/eas-station/blob/main/README.md) | Installation and overview | Everyone |
| [⚡ 5-Minute Quick Start](guides/HELP#getting-started) | Get running immediately | New users |
| [🐳 Portainer Deployment](deployment/PORTAINER_DEPLOYMENT) | Container-based setup | System admins |

## 📊 Visual Documentation

Professional diagrams and flowcharts for system understanding:

| Diagram | Description | Use Case |
|---------|-------------|----------|
| [📊 All Diagrams Index](DIAGRAMS) | Complete visual documentation index | Browse all diagrams |
| [🔄 Alert Processing Pipeline](DIAGRAMS#1-alert-processing-pipeline) | CAP ingestion workflow | Understanding alert flow |
| [📡 EAS Broadcast Workflow](DIAGRAMS#2-eas-broadcast-workflow) | SAME generation & transmission | Operator training |
| [📻 SDR Setup Flow](DIAGRAMS#3-sdr-setup-configuration-flow) | Radio receiver configuration | Hardware setup |
| [🔊 Audio Source Routing](DIAGRAMS#4-audio-source-routing-architecture) | Audio ingestion architecture | Audio troubleshooting |
| [🖥️ Hardware Deployment](DIAGRAMS#5-hardware-deployment-architecture) | Raspberry Pi reference config | Physical installation |

## 👥 User Documentation

### Essential Guides
| Document | Description |
|----------|-------------|
| [📋 Help & Operations Guide](guides/HELP) | Complete operator manual |
| [🛠️ Setup Instructions](guides/SETUP_INSTRUCTIONS) | Initial wizard and environment checklist |
| [🔒 HTTPS Setup](guides/HTTPS_SETUP) | SSL/TLS certificates |
| [🌐 IPAWS Integration](guides/ipaws_feed_integration) | Federal alert source setup |
| [🔄 One-Button Upgrade](guides/one_button_upgrade) | Automated update process |

### Hardware Integration
| Document | Description |
|----------|-------------|
| [📡 SDR Setup Guide](hardware/SDR_SETUP) | Radio receiver configuration |
| [🖥️ Raspberry Pi Build](hardware/reference_pi_build) | Reference hardware configuration |
| [⚡ GPIO Control](hardware/gpio) | Transmitter keying setup |
| [📻 Radio USB Passthrough](hardware/radio_usb_passthrough) | USB radio devices |
| [🔌 Serial Bridge Setup](hardware/SERIAL_ETHERNET_BRIDGE_SETUP) | Lantronix and Linovision adapters |
| [📊 Bill of Materials](hardware/BILL_OF_MATERIALS) | Hardware shopping list |

### Audio System
| Document | Description |
|----------|-------------|
| [🎧 Audio Monitoring Dashboard](audio/AUDIO_MONITORING) | Live stream viewer and troubleshooting |
| [🔊 Professional Audio Subsystem](audio/PROFESSIONAL_AUDIO_SUBSYSTEM) | 24/7 audio monitoring architecture |
| [🎵 Audio Pipeline Architecture](audio/AUDIO_PIPELINE_ARCHITECTURE) | Audio processing internals |
| [📻 Icecast Streaming](audio/ICECAST_STREAMING) | Icecast server setup |
| [📡 iHeartMedia Streams](audio/IHEARTMEDIA_STREAMS) | Commercial stream integration |

### Web Interface & Frontend
| Document | Description |
|----------|-------------|
| [🎨 UI Components Library](frontend/COMPONENT_LIBRARY) | Complete component reference |
| [📱 User Interface Guide](frontend/USER_INTERFACE_GUIDE) | Web interface navigation |
| [🚀 JavaScript API](frontend/JAVASCRIPT_API) | Frontend API documentation |
| [🎨 Theming & Customization](frontend/THEMING_CUSTOMIZATION) | Theme system and branding |
| [📱 Responsive Design Guide](frontend/RESPONSIVE_DESIGN) | Mobile-first design principles |

## 🛠️ Developer Documentation

### Getting Started
| Document | Description |
|----------|-------------|
| [🏗️ Architecture Overview](architecture/THEORY_OF_OPERATION) | System design and components |
| [💻 Development Setup](development/AGENTS) | Local development environment |
| [📋 Contributing Guide](process/CONTRIBUTING) | How to contribute code |
| [✅ Pull Request Process](process/PR_DESCRIPTION) | PR guidelines and templates |

### Architecture & Design
| Document | Description |
|----------|-------------|
| [🏛️ System Architecture](architecture/SYSTEM_ARCHITECTURE) | Overall system design |
| [🔄 Data Flow Sequences](architecture/DATA_FLOW_SEQUENCES) | Data processing workflows |
| [📊 Display System Architecture](architecture/DISPLAY_SYSTEM_ARCHITECTURE) | Display subsystem design |
| [📡 EAS Decoding Summary](architecture/EAS_DECODING_SUMMARY) | Alert decoding internals |

## 🏢 Operational Documentation

### Deployment & Maintenance
| Document | Description |
|----------|-------------|
| [🐳 Docker Deployment](https://github.com/KR8MER/eas-station/blob/main/README.md#-quick-start) | Container setup and management |
| [🚀 Portainer Deployment](deployment/PORTAINER_DEPLOYMENT) | Complete Portainer guide |
| [🗄️ Portainer Database Setup](deployment/portainer/PORTAINER_DATABASE_SETUP) | External database configuration |
| [🌐 Portainer Network Setup](deployment/portainer/PORTAINER_NETWORK_SETUP) | Reverse proxy and DNS guidance |
| [🧰 Post Install Checklist](deployment/post_install) | Finalize services and accounts |
| [🔄 Environment Migration](deployment/ENV_MIGRATION_GUIDE) | Moving between versions |

### Hardware Evaluations
| Document | Description |
|----------|-------------|
| [📡 Hardware SAME Decoder Evaluation](evaluations/HARDWARE_SAME_DECODER_EVALUATION) | Hardware decoder options |
| [🤖 Hailo AI Evaluation](evaluations/HAILO_AI_EVALUATION) | AI accelerator testing |
| [🔌 Zigbee Module Evaluation](evaluations/ZIGBEE_MODULE_EVALUATION) | Zigbee hardware options |
| [📡 Cellular HAT Evaluation](evaluations/CELLULAR_HAT_EVALUATION) | Cellular connectivity options |

### Troubleshooting
| Document | Description |
|----------|-------------|
| [🔧 Common Issues](guides/HELP#troubleshooting) | Solutions for common problems |
| [🗄️ Database Issues](troubleshooting/DATABASE_CONSISTENCY_FIXES) | PostgreSQL/PostGIS troubleshooting |
| [📡 SDR Waterfall Issues](troubleshooting/SDR_WATERFALL_TROUBLESHOOTING) | SDR troubleshooting |
| [🎵 Sample Rate Mismatch](troubleshooting/SAMPLE_RATE_MISMATCH_TROUBLESHOOTING) | Audio sample rate issues |
| [🔌 IPv6 Connectivity](troubleshooting/FIX_IPV6_CONNECTIVITY) | IPv6 network issues |

### Security & Compliance
| Document | Description |
|----------|-------------|
| [🔐 Security Best Practices](security/SECURITY) | Security guidelines |
| [🔒 Password Guide](security/SECURITY_PASSWORD_GUIDE) | Password management |
| [📜 Terms of Use](policies/TERMS_OF_USE) | Usage terms |
| [🔏 Privacy Policy](policies/PRIVACY_POLICY) | Privacy information |

## 📈 Project Information

### Planning & Roadmap
| Document | Description |
|----------|-------------|
| [🗺️ Project Roadmap](roadmap/master_todo) | Current development priorities |
| [🎯 Feature Timeline](roadmap/dasdec3-feature-roadmap) | Release schedule and milestones |
| [🏆 DASDEC3 Comparison](roadmap/DASDEC3_COMPARISON) | Hardware replacement analysis |
| [📋 Project Philosophy](reference/project-philosophy) | Goals and principles |

### Reference Materials
| Document | Description |
|----------|-------------|
| [📖 About EAS Station](reference/ABOUT) | Project background and goals |
| [📄 Changelog](reference/CHANGELOG) | Version history and changes |
| [📡 EAS Event Codes](reference/EAS_EVENT_CODES_COMPLETE) | Complete event code list |
| [🎵 New Features (2025-11)](reference/NEW_FEATURES_2025-11) | Recent features |
| [📋 Project Philosophy](reference/project-philosophy) | Goals and principles |
| [📊 Setup Wizard Reference](reference/SETUP_WIZARD) | Setup wizard technical details |
| [📅 RWT Scheduling](reference/RWT_SCHEDULING) | Required Weekly Test scheduling |
| [📄 Alert PDF Export](reference/alerts-pdf-export) | PDF export functionality |
| [🗃️ Documentation Archive](archive/README) | Historical analyses and reports |

## 📁 File Organization

```
docs/
├── guides/              # Essential user guides (5 files)
├── hardware/            # Hardware setup and configuration
├── audio/               # Audio system documentation
├── frontend/            # Web UI and frontend docs
├── development/         # Developer documentation
├── architecture/        # System architecture docs
├── deployment/          # Deployment guides
├── evaluations/         # Hardware evaluation reports
├── troubleshooting/     # Problem-solving guides
├── security/            # Security documentation
├── reference/           # Technical reference materials
├── roadmap/             # Project planning and milestones
├── policies/            # Project policies and governance
├── process/             # Development processes
├── resources/           # Vendor documentation and PDFs
└── archive/             # Historical documentation
```

## 🔍 Finding Information

### By User Type
- **🎯 New Users**: Start with [Quick Start](#quick-start)
- **👨‍💻 Operators**: See [Help & Operations Guide](guides/HELP)
- **🔧 System Admins**: Check [Deployment Guides](#deployment--maintenance)
- **💻 Developers**: Review [Development Setup](development/AGENTS)

### By Task
- **🚀 Installation**: [Quick Start](#quick-start)
- **⚙️ Configuration**: [Essential Guides](#essential-guides)
- **🔧 Troubleshooting**: [Troubleshooting Section](#troubleshooting)
- **🛠️ Development**: [Developer Documentation](#developer-documentation)
- **📈 Project Info**: [Project Information](#project-information)

## 🆘 Getting Help

1. **Check Documentation**: Start with the relevant guide above
2. **Search Issues**: [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
3. **Review Logs**: Check application logs with `docker compose logs -f`
4. **Community Support**: [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)

## 📊 Documentation Statistics

| Metric | Value |
|--------|-------|
| Essential User Guides | 5 |
| Essential References | 9 |
| Hardware Guides | 10 |
| Audio Documentation | 6 |
| Developer Documentation | 18 |
| Archived Historical Docs | 20+ |
| Total Documentation Directories | 14 |

## 🧭 Navigation Tips

- **Use Ctrl+F / Cmd+F** on this page to search for any keyword
- **Start with [Main README](https://github.com/KR8MER/eas-station/blob/main/README.md)** for visual navigation
- **Bookmark frequently used guides** from the web interface
- **Check [CHANGELOG](reference/CHANGELOG)** for recent changes
- **Read [Development Guide](development/AGENTS)** before contributing code

---

**Last Updated**: 2025-11-25
**Version**: 3.0 (Reorganized Structure)
**For questions or contributions, see the [Contributing Guide](process/CONTRIBUTING)**
