# EAS Station™ Documentation

Welcome to the documentation for EAS Station™ - an Emergency Alert System platform.

> **IMPORTANT**: This software is experimental and for laboratory use only. Not FCC-certified for production emergency alerting.

---

## Getting Started

1. **[Installation](../README.md#quick-start)** - One command to get running
2. **[Setup Wizard](guides/SETUP_INSTRUCTIONS.md)** - First-run configuration
3. **[User Guide](guides/HELP.md)** - Daily operations

---

## Documentation by Role

### For Operators

| Guide | What You'll Learn |
|-------|-------------------|
| [User Guide](guides/HELP.md) | Dashboard, alerts, monitoring |
| [Setup Instructions](guides/SETUP_INSTRUCTIONS.md) | First-time configuration |
| [HTTPS Setup](guides/HTTPS_SETUP.md) | Secure access configuration |
| [Pre/Post-Alert Signaling](guides/ALERT_SIGNALS.md) | Configure pre/post-broadcast signals (bell, beep, three-tone, QC-II, DTMF, MDC1200) |
| [Local Authority EAS Access](guides/LOCAL_AUTHORITIES.md) | Delegate restricted EAS origination to local authorities |

### For Administrators

| Guide | What You'll Learn |
|-------|-------------------|
| [Installation Guide](installation/QUICKSTART.md) | Bare metal deployment |
| [SDR Setup](hardware/SDR_SETUP.md) | Radio receiver configuration |
| [Firewall Requirements](troubleshooting/FIREWALL_REQUIREMENTS.md) | Network port configuration |
| [Application Settings](guides/APPLICATION_SETTINGS.md) | Logging, storage paths, branding, password policy |
| [Health Monitoring Endpoints](guides/HEALTH_MONITORING.md) | REST health checks for external monitoring |

### For Developers

| Guide | What You'll Learn |
|-------|-------------------|
| [Developer Guidelines](development/AGENTS.md) | Code standards, architecture, testing |
| [Large File Refactor Plan](development/LARGE_FILE_REFACTOR_PLAN.md) | Which oversized modules are being split, how, and what has landed |
| [JavaScript API](frontend/JAVASCRIPT_API.md) | Frontend JS globals (`EASApi`, `EASWebSocket`, ...) — not the backend REST API |
| **API Reference** (in the running app, `/api-reference`) | Live reference of every `/api/*` route, generated from `app.url_map` on each request — never a stale hand-maintained list |
| [API Key Management](guides/API_KEY_MANAGEMENT.md) | Planned key-based auth for external API access — **not yet implemented** |
| [Contributing](process/CONTRIBUTING.md) | How to contribute |

---

## System Overview

EAS Station™ integrates multiple alert sources (NOAA Weather, IPAWS Federal) and processes them through a pipeline that includes:

- Multi-source alert aggregation
- FCC-compliant SAME encoding
- PostGIS spatial filtering
- SDR broadcast verification
- Built-in HTTPS with Let's Encrypt
- GPIO relay and LED sign control

**[View Full Architecture Details](architecture/SYSTEM_ARCHITECTURE.md)** | **[View Diagrams](reference/DIAGRAMS.md)**

---

## Documentation Structure

| Directory | Contents |
|-----------|----------|
| `architecture/` | System architecture and design |
| `audio/` | Audio monitoring |
| `development/` | Developer documentation |
| `frontend/` | Web UI documentation |
| `guides/` | User and operator guides |
| `hardware/` | SDR and hardware setup |
| `installation/` | Installation guides |
| `maintenance/` | System maintenance |
| `policies/` | Legal documents |
| `process/` | Contributing and certification |
| `reference/` | Reference materials |
| `security/` | Security documentation |
| `troubleshooting/` | Problem-solving guides |

---

## Common Tasks

### Setup & Configuration

- [Install EAS Station™](../README.md#quick-start)
- [Configure SDR receivers](hardware/SDR_SETUP.md)
- [Set up HTTPS](guides/HTTPS_SETUP.md)
- [Connect to IPAWS](guides/ipaws_feed_integration.md)

### Daily Operations

- [Monitor alerts](guides/HELP.md#monitoring-alerts)
- [Manage boundaries](guides/HELP.md#managing-boundaries-and-alerts)
- [View audio streams](audio/AUDIO_MONITORING.md)
- [Check system health](guides/HELP.md#routine-operations)

### Troubleshooting

- [SDR not detecting](hardware/SDR_SETUP.md#troubleshooting)
- [Audio problems](audio/AUDIO_MONITORING.md#troubleshooting)
- [Audio/SDR sample-rate fix tool](troubleshooting/AUDIO_SDR_FIX_TOOL.md)
- [Common errors](guides/HELP.md#troubleshooting)

---

## Getting Help

1. **Check the documentation** - Start with the [User Guide](guides/HELP.md)
2. **Review troubleshooting** - See [Common Issues](guides/HELP.md#troubleshooting)
3. **Run diagnostics** - Use built-in diagnostic tools
4. **Ask for help** - [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)
5. **Report bugs** - [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
6. **Contact** - [sales@easstation.com](mailto:sales@easstation.com) · (419) 890-1890 (general/licensing) · [security@easstation.com](mailto:security@easstation.com) (security)

---

## Project Information

| Resource | Link |
|----------|------|
| **About** | [Project Overview](reference/ABOUT.md) |
| **Changelog** | [Version History](reference/CHANGELOG.md) |
| **License** | [AGPL v3](../LICENSE) (Open Source) / [Commercial](../LICENSE-COMMERCIAL) |

### Legal & Compliance

- [Terms of Use](policies/TERMS_OF_USE.md)
- [Privacy Policy](policies/PRIVACY_POLICY.md)
- [FCC Compliance Information](reference/ABOUT.md#legal--compliance)

---

## Contributing

- [Contributing Guide](process/CONTRIBUTING.md)
- [Developer Guidelines](development/AGENTS.md)

---

**Last Updated**: 2026-06-10

**[Return to Main README](../README.md)**
