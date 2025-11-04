# Managing Alerts

Learn how to configure alert sources, manage boundaries, and respond to emergency alerts.

## Alert Sources

### Configuring NOAA Weather Alerts

1. Navigate to **Admin → Alert Sources**
2. Click **Add Source**
3. Select **NOAA CAP**
4. Choose state(s)
5. Set poll interval (default: 180 seconds)
6. Click **Save**

### Configuring IPAWS

1. Navigate to **Admin → Alert Sources**
2. Click **Add Source**
3. Select **IPAWS**
4. Configure feed URL
5. Click **Save**

## Alert Filtering

Use geographic boundaries to filter alerts:

See [Geographic Boundaries](boundaries.md) for detailed configuration.

## Alert Actions

### View Alert Details
Click any alert to see:
- Full alert text
- Geographic coverage
- SAME codes
- Effective/expiration times
- Event type and severity

### Generate SAME Audio
For authorized event types:
1. Select alert
2. Click **Generate SAME Audio**
3. Audio file created in `EAS_OUTPUT_DIR`

### Manual Broadcast
To manually broadcast an alert:
1. Navigate to **Admin → Manual Broadcast**
2. Select or create alert
3. Configure SAME parameters
4. Click **Broadcast** (test environment only!)

!!! warning "FCC Compliance"
    Never broadcast EAS tones on production systems without proper authorization.

## Troubleshooting

See [Troubleshooting Guide](troubleshooting.md) for common issues.
