# Getting Started with EAS Station

Welcome to EAS Station! This guide will help you get your Emergency Alert System up and running quickly.

## Overview

Getting started with EAS Station involves:

1. **Installation** - Deploy using Docker
2. **Configuration** - Set up database and environment
3. **First Alert** - Configure your first alert source
4. **Verification** - Test the system end-to-end

Expected time: **15-30 minutes**

## Prerequisites

Before you begin, ensure you have:

- [x] **Docker Engine 24+** with Docker Compose V2
- [x] **PostgreSQL 14+** with PostGIS extension (can be containerized)
- [x] **4GB RAM** minimum (8GB recommended)
- [x] **Internet connection** for downloading images and polling alerts
- [x] **Basic command line** familiarity

!!! tip "Hardware Setup"
    For SDR receivers, GPIO control, and LED signs, see the [Hardware Setup](../user-guide/hardware/index.md) guides after completing basic installation.

## Installation Paths

Choose the installation method that best fits your needs:

<div class="grid cards" markdown>

-   :material-clock-fast:{ .lg .middle } **Quick Start**

    ---

    One-command installation for development and testing

    [:octicons-arrow-right-24: Quick Start](quick-start.md)

-   :material-docker:{ .lg .middle } **Docker Installation**

    ---

    Step-by-step Docker deployment

    [:octicons-arrow-right-24: Installation Guide](installation.md)

-   :material-cog:{ .lg .middle } **Initial Configuration**

    ---

    Configure environment variables and database

    [:octicons-arrow-right-24: Configuration](configuration.md)

-   :material-alert:{ .lg .middle } **First Alert**

    ---

    Set up your first alert source and test

    [:octicons-arrow-right-24: First Alert](first-alert.md)

</div>

## Quick Navigation

| I want to... | Guide |
|--------------|-------|
| Get running immediately | [Quick Start](quick-start.md) |
| Understand the installation process | [Installation Guide](installation.md) |
| Configure environment variables | [Configuration](configuration.md) |
| Set up my first alert source | [First Alert](first-alert.md) |
| Deploy with Portainer | [Portainer Guide](../admin-guide/deployment/portainer.md) |
| Set up hardware (SDR, GPIO) | [Hardware Setup](../user-guide/hardware/index.md) |

## What's Next?

After completing the getting started guides:

1. **Explore the Interface** - [Dashboard Overview](../user-guide/dashboard.md)
2. **Configure Alert Sources** - [Managing Alerts](../user-guide/alerts.md)
3. **Set Up Geographic Boundaries** - [Boundaries Guide](../user-guide/boundaries.md)
4. **Configure Hardware** - [Hardware Setup](../user-guide/hardware/index.md)

## Need Help?

If you encounter issues during setup:

- 📖 Check [Troubleshooting](../user-guide/troubleshooting.md)
- 🔍 Search [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
- 💬 Ask in [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)

---

Ready to begin? Start with the [Quick Start Guide](quick-start.md) →
