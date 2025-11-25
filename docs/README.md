# 📚 EAS Station Documentation

**Welcome!** This is your complete guide to the EAS Station emergency alert system.

> ⚠️ **IMPORTANT**: This software is experimental and for laboratory use only. Not FCC-certified for production emergency alerting.

---

## 🚀 Getting Started

```mermaid
flowchart LR
    NEW[New User?] --> INSTALL[1. Install]
    INSTALL --> CONFIG[2. Configure]
    CONFIG --> TEST[3. Test]
    TEST --> OPERATE[4. Daily Use]

    style NEW fill:#3b82f6,color:#fff
    style OPERATE fill:#10b981,color:#fff
```

**5-Minute Quick Start:**
1. **[Installation](../README.md#quick-start)** - One command to get running
2. **[Setup Wizard](guides/SETUP_INSTRUCTIONS)** - First-run configuration
3. **[User Guide](guides/HELP)** - Daily operations

---

## 📖 Documentation by Role

### 🎯 For Operators

**Daily operations and monitoring**

| Guide | What You'll Learn |
|-------|-------------------|
| **[User Guide](guides/HELP)** | Dashboard, alerts, monitoring |
| **[Audio Monitoring](audio/AUDIO_MONITORING)** | Live audio streams, troubleshooting |
| **[Setup Instructions](guides/SETUP_INSTRUCTIONS)** | First-time configuration |

### 🔧 For Administrators

**Deployment, security, and maintenance**

| Guide | What You'll Learn |
|-------|-------------------|
| **[Portainer Deployment](guides/PORTAINER_DEPLOYMENT)** | Complete deployment guide |
| **[SDR Setup](hardware/SDR_SETUP)** | Radio receiver configuration |
| **[HTTPS Setup](guides/HTTPS_SETUP)** | SSL/TLS certificates |
| **[Database Setup](guides/DATABASE_CONSISTENCY_FIXES)** | PostgreSQL troubleshooting |

### 💻 For Developers

**Architecture, APIs, and contributing**

| Guide | What You'll Learn |
|-------|-------------------|
| **[Developer Guidelines](development/AGENTS)** | Code standards, architecture, testing |
| **[Frontend Documentation](frontend/FRONTEND_INDEX)** | UI components, theming |
| **[JavaScript API](frontend/JAVASCRIPT_API)** | REST API reference |
| **[Contributing](process/CONTRIBUTING)** | How to contribute |

---

## 🗺️ System Overview

### Architecture

```mermaid
graph TB
    subgraph "Alert Sources"
        NOAA[NOAA Weather]
        IPAWS[IPAWS Federal]
    end

    subgraph "Processing"
        POLL[Alert Poller]
        DB[(PostgreSQL<br/>+ PostGIS)]
        WEB[Web Interface]
    end

    subgraph "Output"
        AUDIO[Audio Service]
        GPIO[GPIO Relays]
        LED[LED Signs]
    end

    NOAA --> POLL
    IPAWS --> POLL
    POLL --> DB
    DB --> WEB
    DB --> AUDIO
    AUDIO --> GPIO
    AUDIO --> LED

    style NOAA fill:#3b82f6,color:#fff
    style IPAWS fill:#3b82f6,color:#fff
    style DB fill:#8b5cf6,color:#fff
    style WEB fill:#10b981,color:#fff
    style AUDIO fill:#f59e0b,color:#000
```

**[View Full Architecture Details →](architecture/SYSTEM_ARCHITECTURE)**

### Key Features

- 🌐 Multi-source alert aggregation (NOAA, IPAWS, custom)
- 📻 FCC-compliant SAME encoding
- 🗺️ PostGIS spatial filtering
- 📡 SDR broadcast verification
- 🔒 Built-in HTTPS with Let's Encrypt
- ⚡ GPIO relay and LED sign control

---

## 📂 Documentation Structure

```
docs/
├── guides/              ← How-to guides for operators
├── hardware/            ← SDR, GPIO, Raspberry Pi setup
├── audio/               ← Audio system documentation
├── development/         ← Developer documentation
├── architecture/        ← System design and theory
├── deployment/          ← Deployment guides
├── reference/           ← Technical reference
└── roadmap/             ← Future features
```

**[Complete Index](INDEX)** - Searchable list of all topics

---

## 🎯 Common Tasks

### Setup & Configuration

- [Install EAS Station](../README.md#quick-start)
- [Configure SDR receivers](hardware/SDR_SETUP)
- [Set up HTTPS](guides/HTTPS_SETUP)
- [Connect to IPAWS](guides/ipaws_feed_integration)

### Daily Operations

- [Monitor alerts](guides/HELP#monitoring-alerts)
- [Manage boundaries](guides/HELP#managing-boundaries-and-alerts)
- [View audio streams](audio/AUDIO_MONITORING)
- [Check system health](guides/HELP#routine-operations)

### Troubleshooting

- [Database connection issues](guides/DATABASE_CONSISTENCY_FIXES)
- [SDR not detecting](hardware/SDR_SETUP#troubleshooting)
- [Audio problems](audio/AUDIO_MONITORING#troubleshooting)
- [Common errors](guides/HELP#troubleshooting)

---

## 🆘 Getting Help

```mermaid
flowchart LR
    ISSUE{Having<br/>an issue?}
    ISSUE -->|Installation| SETUP[Setup Instructions]
    ISSUE -->|Hardware| SDR[SDR Setup Guide]
    ISSUE -->|Operation| HELP[User Guide]
    ISSUE -->|Still stuck| GH[GitHub Issues]

    style ISSUE fill:#ef4444,color:#fff
    style GH fill:#3b82f6,color:#fff
```

1. **Check the documentation** - Start with [INDEX](INDEX)
2. **Review troubleshooting** - See [Common Issues](guides/HELP#troubleshooting)
3. **Run diagnostics** - Use built-in diagnostic tools
4. **Ask for help** - [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)
5. **Report bugs** - [GitHub Issues](https://github.com/KR8MER/eas-station/issues)

---

## 📊 Project Information

| Resource | Link |
|----------|------|
| **About** | [Project Overview](reference/ABOUT) |
| **Changelog** | [Version History](reference/CHANGELOG) |
| **Roadmap** | [Future Features](roadmap/master_todo) |
| **License** | [AGPL v3](../LICENSE) (Open Source) / [Commercial](../LICENSE-COMMERCIAL) |

### Legal & Compliance

- [Terms of Use](policies/TERMS_OF_USE)
- [Privacy Policy](policies/PRIVACY_POLICY)
- [FCC Compliance Information](reference/ABOUT#legal--compliance)

---

## 🤝 Contributing

We welcome contributions! See:

- [Contributing Guide](process/CONTRIBUTING)
- [Developer Guidelines](development/AGENTS)
- [Code Standards](development/AGENTS#code-standards)

---

**Last Updated**: 2025-11-25
**Documentation Version**: 2.1.x+

**[Return to Main README](../README.md)** | **[View Complete Index](INDEX)**
