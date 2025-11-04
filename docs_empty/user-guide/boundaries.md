# Geographic Boundaries

Configure geographic boundaries for precise alert filtering.

## Overview

Geographic boundaries allow you to:
- Filter alerts by county, state, or custom polygons
- Define multiple coverage areas
- Include/exclude specific regions
- Visualize coverage on maps

## Creating Boundaries

### County Boundary

1. Navigate to **Admin → Boundaries**
2. Click **Add Boundary**
3. Configure:
   - **Name**: My County
   - **Type**: County
   - **State**: XX
   - **County**: County Name
4. Click **Save**

### State Boundary

1. Click **Add Boundary**
2. Configure:
   - **Name**: My State
   - **Type**: State
   - **State**: XX
3. Click **Save**

### Custom Polygon

1. Click **Add Boundary**
2. Configure:
   - **Name**: Custom Area
   - **Type**: Polygon
3. Draw polygon on map
4. Click **Save**

## Boundary Filtering

Enable filtering on alert sources:

1. Navigate to **Admin → Alert Sources**
2. Edit source
3. Check **"Filter by Boundaries"**
4. Select boundaries to include
5. Click **Save**

## SAME Code Mapping

Boundaries automatically map to SAME codes:
- County codes (e.g., OHC137)
- Zone codes (e.g., OHZ016)
- State codes (e.g., OHS)

## Best Practices

- Start with state-wide coverage
- Add county boundaries for local focus
- Test filtering with active alerts
- Review coverage regularly

See [Managing Alerts](alerts.md) for alert configuration.
