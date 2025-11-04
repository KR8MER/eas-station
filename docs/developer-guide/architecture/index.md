# Architecture

EAS Station system architecture and design documentation.

## Architecture Topics

- [System Overview](overview.md) - High-level architecture and design patterns
- [Theory of Operation](theory.md) - Detailed explanation of system operation
- [Components](components.md) - Core components and modules

## System Design

EAS Station is built with a modular architecture:

**Backend**: Python 3.11 with Flask 3.0 providing REST APIs and business logic.

**Database**: PostgreSQL 17 with PostGIS 3.4 for data persistence and geographic operations.

**Frontend**: Bootstrap 5 with Highcharts and Leaflet for responsive UI and visualization.

**Deployment**: Containerized with Docker for consistent deployment across environments.

## Key Design Principles

- **Modularity**: Independent components for alerts, audio, hardware control
- **Extensibility**: Plugin architecture for custom alert sources and outputs
- **Reliability**: Error handling, logging, and recovery mechanisms
- **Performance**: Efficient database queries and caching strategies
- **Scalability**: Designed to handle multiple alert sources and high alert volumes

## Component Overview

**Alert Processing**: Ingests and processes SAME/EAS alerts from various sources.

**Audio Pipeline**: Captures, decodes, and archives audio from SDR and other sources.

**Hardware Control**: Manages GPIO relays, LED signs, and other output devices.

**Web Interface**: Real-time dashboard for monitoring and managing the system.

## Development

For development setup, see the [Development Setup](../setup.md) guide.
