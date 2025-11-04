# Database Management

PostgreSQL database administration for EAS Station.

## Database Topics

- [Setup & Configuration](setup.md) - Initial PostgreSQL configuration and PostGIS setup
- [Maintenance](maintenance.md) - Backups, optimization, and monitoring
- [Troubleshooting](troubleshooting.md) - Common database issues and solutions

## Overview

EAS Station uses PostgreSQL 17 with PostGIS 3.4 for storing:

- Alert data and history
- Geographic boundaries (FIPS codes, counties, zones)
- Audio source configurations
- System settings and user data

## Requirements

- PostgreSQL 17+
- PostGIS 3.4+
- Sufficient disk space for alert history
- Regular backup strategy

## Best Practices

- Enable automated backups
- Monitor database size and performance
- Regularly vacuum and analyze tables
- Keep PostgreSQL and PostGIS updated
- Use connection pooling for better performance
