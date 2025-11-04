# System Configuration

Configure EAS Station for your specific needs.

## Configuration Topics

- [Environment Variables](environment.md) - Complete environment variable reference
- [Alert Sources](sources.md) - Configure NOAA, IPAWS, and custom alert feeds
- [Performance Tuning](performance.md) - Optimize system performance for your workload

## Configuration Files

EAS Station is configured primarily through environment variables, which can be set in:

- `.env` file for Docker Compose deployments
- Container environment for direct Docker usage
- System environment for standalone installations

## Quick Configuration

For initial setup, see [Initial Configuration](../../getting-started/configuration.md).

## Key Configuration Areas

**Alert Sources**: Configure which alert feeds to monitor (NOAA Weather Radio, IPAWS, custom sources).

**Geographic Boundaries**: Define which counties, states, or zones to monitor for alerts.

**Audio Sources**: Set up SDR receivers, audio inputs, and output devices.

**System Settings**: Configure logging, database connections, and system behavior.

## Next Steps

After configuration:

1. Test your alert sources
2. Verify geographic boundaries
3. Review [Performance Tuning](performance.md) options
4. Set up monitoring and logging
