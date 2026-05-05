# EAS Station Documentation

Welcome to the documentation for EAS Station - an Emergency Alert System platform.

> **IMPORTANT**: This software is experimental and for laboratory use only. Not FCC-certified for production emergency alerting.

---

## Getting Started

1. **[Installation](../README.md#quick-start)** - One command to get running
2. **[Setup Wizard](guides/SETUP_INSTRUCTIONS)** - First-run configuration
3. **[User Guide](guides/HELP)** - Daily operations

---

## Documentation by Role

### For Operators

| Guide | What You'll Learn |
|-------|-------------------|
| [User Guide](guides/HELP) | Dashboard, alerts, monitoring |
| [Setup Instructions](guides/SETUP_INSTRUCTIONS) | First-time configuration |
| [HTTPS Setup](guides/HTTPS_SETUP) | Secure access configuration |
| [Pre/Post-Alert Signaling](guides/ALERT_SIGNALS) | Configure pre/post-broadcast signals (bell, beep, three-tone, QC-II, DTMF, MDC1200) |

### For Administrators

| Guide | What You'll Learn |
|-------|-------------------|
| [Installation Guide](installation/README) | Bare metal deployment |
| [SDR Setup](hardware/SDR_SETUP) | Radio receiver configuration |
| [Firewall Requirements](troubleshooting/FIREWALL_REQUIREMENTS) | Network port configuration |

### For Developers

| Guide | What You'll Learn |
|-------|-------------------|
| [Developer Guidelines](development/AGENTS) | Code standards, architecture, testing |
| [JavaScript API](frontend/JAVASCRIPT_API) | REST API reference |
| [Contributing](process/CONTRIBUTING) | How to contribute |

---

## System Overview

EAS Station integrates multiple alert sources (NOAA Weather, IPAWS Federal) and processes them through a pipeline that includes:

- Multi-source alert aggregation
- FCC-compliant SAME encoding
- PostGIS spatial filtering
- SDR broadcast verification
- Built-in HTTPS with Let's Encrypt
- GPIO relay and LED sign control

**[View Full Architecture Details](architecture/SYSTEM_ARCHITECTURE)** | **[View Diagrams](reference/DIAGRAMS)**

---

## Documentation Structure

```
docs/
├── architecture/    # System architecture and design
├── audio/           # Audio monitoring
├── development/     # Developer documentation
├── frontend/        # Web UI documentation
├── guides/          # User and operator guides
├── hardware/        # SDR and hardware setup
├── installation/    # Installation guides
├── maintenance/     # System maintenance
├── policies/        # Legal documents
├── process/         # Contributing and certification
├── reference/       # Reference materials
├── roadmap/         # Feature planning
├── security/        # Security documentation
└── troubleshooting/ # Problem-solving guides
```

**[Complete Index](INDEX)** - Full list of all documentation

---

## Common Tasks

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

- [SDR not detecting](hardware/SDR_SETUP#troubleshooting)
- [Audio problems](audio/AUDIO_MONITORING#troubleshooting)
- [Common errors](guides/HELP#troubleshooting)

---

## Getting Help

1. **Check the documentation** - Start with [INDEX](INDEX)
2. **Review troubleshooting** - See [Common Issues](guides/HELP#troubleshooting)
3. **Run diagnostics** - Use built-in diagnostic tools
4. **Ask for help** - [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)
5. **Report bugs** - [GitHub Issues](https://github.com/KR8MER/eas-station/issues)

---

## Project Information

| Resource | Link |
|----------|------|
| **About** | [Project Overview](reference/ABOUT) |
| **Changelog** | [Version History](reference/CHANGELOG) |
| **Roadmap** | [Future Features](roadmap/dasdec3-feature-roadmap) |
| **License** | [AGPL v3](../LICENSE) (Open Source) / [Commercial](../LICENSE-COMMERCIAL) |

### Legal & Compliance

- [Terms of Use](policies/TERMS_OF_USE)
- [Privacy Policy](policies/PRIVACY_POLICY)
- [FCC Compliance Information](reference/ABOUT#legal--compliance)

---

## Contributing

- [Contributing Guide](process/CONTRIBUTING)
- [Developer Guidelines](development/AGENTS)

---

**Last Updated**: 2026-02-13

**[Return to Main README](../README.md)** | **[View Complete Index](INDEX)**
