# Troubleshooting Guide

Common issues and solutions for EAS Station.

## Database Issues

### Connection Failed

**Symptoms**: "Database connection failed" error

**Solutions:**

1. Check database is running:
   ```bash
   docker compose ps alerts-db
   ```

2. Verify credentials in `.env`:
   ```bash
   POSTGRES_HOST=alerts-db
   POSTGRES_PASSWORD=correct-password
   ```

3. Test connection:
   ```bash
   docker compose exec eas-station python -c "
   from app_core.models import db
   print('Connected!' if db.engine else 'Failed')
   "
   ```

### PostGIS Extension Missing

**Symptoms**: "PostGIS extension not found"

**Solution:**

```bash
docker compose exec alerts-db psql -U postgres -d alerts -c "CREATE EXTENSION postgis;"
```

## Alert Polling Issues

### No Alerts Appearing

**Possible causes:**

1. **Polling not started** - Check logs:
   ```bash
   docker compose logs -f eas-station | grep poll
   ```

2. **No active alerts** - Verify at [alerts.weather.gov](https://alerts.weather.gov/)

3. **Network issues** - Test connectivity:
   ```bash
   docker compose exec eas-station curl -I https://api.weather.gov
   ```

4. **Rate limiting** - Increase `POLL_INTERVAL_SEC` in `.env`

### API Errors

**HTTP 403 Forbidden**:
- Check `NOAA_USER_AGENT` is properly configured
- Ensure it includes contact information

**HTTP 429 Too Many Requests**:
- Increase polling interval
- Check for duplicate pollers

## Audio Issues

### TTS Not Working

**Azure OpenAI TTS:**

1. Verify API credentials:
   ```bash
   AZURE_OPENAI_ENDPOINT=https://your-instance.openai.azure.com/
   AZURE_OPENAI_KEY=valid-key
   ```

2. Test endpoint:
   ```bash
   curl -H "api-key: $AZURE_OPENAI_KEY" $AZURE_OPENAI_ENDPOINT/openai/deployments
   ```

### SAME Generation Failed

**Check logs for errors:**
```bash
docker compose logs eas-station | grep -i same
```

**Common issues:**
- Invalid FIPS codes
- Missing event codes
- Audio library errors

## Hardware Issues

### GPIO Errors

**Raspberry Pi GPIO not working:**

1. Ensure `RPi.GPIO` is installed
2. Check pin numbering (BCM vs BOARD)
3. Verify permissions
4. Test pin:
   ```python
   import RPi.GPIO as GPIO
   GPIO.setmode(GPIO.BCM)
   GPIO.setup(17, GPIO.OUT)
   GPIO.output(17, GPIO.HIGH)
   ```

### SDR Not Detected

**Check USB device:**
```bash
lsusb | grep -i rtl
```

**Pass through to Docker:**

In `docker-compose.yml`:
```yaml
devices:
  - /dev/bus/usb:/dev/bus/usb
```

### LED Sign Not Responding

1. Verify IP and port:
   ```bash
   ping $LED_SIGN_IP
   telnet $LED_SIGN_IP $LED_SIGN_PORT
   ```

2. Check network connectivity
3. Verify Alpha Protocol compatibility
4. Review LED sign logs

## Performance Issues

### High Memory Usage

1. Check Docker resource limits
2. Reduce `MAX_WORKERS`
3. Lower `CACHE_TIMEOUT`
4. Monitor database size

### Slow Dashboard

1. Clear browser cache
2. Reduce alert history
3. Optimize database indexes
4. Check network latency

## Container Issues

### Container Won't Start

**Check logs:**
```bash
docker compose logs eas-station
```

**Common issues:**
- Port conflicts (change port in `docker-compose.yml`)
- Volume permission errors
- Missing environment variables
- Out of disk space

### Build Failures

**Clear Docker cache:**
```bash
docker compose build --no-cache
```

**Check disk space:**
```bash
docker system df
```

## Logging

### Enable Debug Logging

In `.env`:
```bash
LOG_LEVEL=DEBUG
```

Restart:
```bash
docker compose restart
```

### View Logs

**Real-time:**
```bash
docker compose logs -f
```

**Specific service:**
```bash
docker compose logs -f eas-station
```

**Last 100 lines:**
```bash
docker compose logs --tail=100
```

## Getting More Help

If issues persist:

1. **Check Documentation**: Review relevant guides
2. **Search Issues**: [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
3. **Ask Community**: [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)
4. **Report Bug**: Open new issue with logs and configuration (redact secrets)

### Information to Include

When reporting issues:

- EAS Station version
- Docker version
- Operating system
- Error messages (full text)
- Relevant logs
- Configuration (redact passwords/keys)
- Steps to reproduce
