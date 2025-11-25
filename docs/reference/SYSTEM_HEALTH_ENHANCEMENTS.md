# System Health Enhancements

## Overview

Enhanced the system_health page with shields.io badges and Linux distribution logos to provide a more professional and visually appealing interface.

## Visual Preview

The system health page header now displays:

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  [Ubuntu Logo]  🏥 System Health Monitor                                  ┃
┃                                                                            ┃
┃  Comprehensive monitoring of system resources, hardware, and container    ┃
┃  health                                                                    ┃
┃                                                                            ┃
┃  ╔════════════════════════════════════════════════════════════════════╗  ┃
┃  ║  Badges (shields.io):                                              ║  ┃
┃  ║                                                                     ║  ┃
┃  ║  [OS: Ubuntu 22.04] [Kernel: 5.15.0] [Arch: x86_64]               ║  ┃
┃  ║  [Cores: 4p/8t] [CPU: 45%] [Memory: 65%] [Uptime: 1d 5h]         ║  ┃
┃  ╚════════════════════════════════════════════════════════════════════╝  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

## Features Implemented

### 1. Distribution Logo Display

Automatically detects and displays the Linux distribution logo in the page header.

**Supported Distributions:**
- Ubuntu
- Debian
- Fedora
- CentOS
- RHEL (Red Hat Enterprise Linux)
- Arch Linux
- Alpine Linux
- openSUSE
- Raspbian

The logo gracefully falls back if unavailable (using `onerror` handler).

### 2. Shields.io Badges

Dynamic badges powered by shields.io that update in real-time:

#### OS Badge
- **Format:** `OS - {Distribution} {Version}`
- **Icon:** Linux logo
- **Color:** Blue
- **Example:** `OS - Ubuntu 22.04`

#### Kernel Badge
- **Format:** `Kernel - {Version}`
- **Color:** Light grey
- **Example:** `Kernel - 5.15.0`

#### Architecture Badge
- **Format:** `Arch - {Architecture}`
- **Color:** Informational (blue)
- **Example:** `Arch - x86_64`

#### CPU Cores Badge
- **Format:** `Cores - {Physical}p/{Logical}t`
- **Color:** Informational (blue)
- **Example:** `Cores - 4p/8t`

#### CPU Usage Badge
- **Format:** `CPU - {Usage}%`
- **Icon:** Intel logo
- **Color:** 
  - Green (0-50%): Normal operation
  - Yellow (50-80%): Moderate load
  - Red (80-100%): High load
- **Example:** `CPU - 45%`

#### Memory Usage Badge
- **Format:** `Memory - {Usage}%`
- **Icon:** Memory chip
- **Color:**
  - Green (0-75%): Normal operation
  - Yellow (75-90%): Moderate usage
  - Red (90-100%): Critical usage
- **Example:** `Memory - 65%`

#### Uptime Badge
- **Format:** `Uptime - {Days}d {Hours}h` or `{Hours}h` for < 1 day
- **Color:** Green (success)
- **Example:** `Uptime - 1d 5h`

### 3. Auto-Refresh Functionality

- Badges update automatically every 30 seconds
- Manual refresh button still available
- Dynamic updates without full page reload
- Uses JavaScript to update badge URLs on the fly

## Technical Implementation

### Backend Changes (`app_utils/system.py`)

#### New Functions

1. **`get_distro_logo_url(distro_id: Optional[str]) -> Optional[str]`**
   - Maps Linux distribution IDs to logo URLs
   - Returns None if distribution not found
   - Supports partial matching for flexibility

2. **`get_shields_io_badges(health_data: Dict[str, Any]) -> Dict[str, str]`**
   - Generates shields.io badge URLs based on system metrics
   - Returns dictionary of badge URLs keyed by type
   - Automatically applies color coding based on thresholds
   - URL-encodes labels for proper rendering

#### Modified Functions

- **`build_system_health_snapshot()`**
  - Now includes `shields_badges` key with badge URLs
  - Now includes `distro_logo_url` key with logo URL
  - Maintains backward compatibility with existing code

### Frontend Changes (`templates/system_health.html`)

#### CSS Additions

```css
.badge-showcase { 
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
    padding: 1rem;
    background: rgba(255, 255, 255, 0.03);
    border-radius: var(--radius-md);
    margin-top: 1rem;
}

.badge-showcase img {
    height: 20px;
    transition: transform 0.2s;
}

.badge-showcase img:hover {
    transform: scale(1.05);
}

.distro-logo {
    height: 48px;
    width: auto;
    margin-right: 1rem;
    filter: brightness(1.1);
}
```

#### Template Structure

```html
<div class="d-flex align-items-center mb-3">
    {% if distro_logo_url %}
    <img src="{{ distro_logo_url }}" alt="Distribution Logo" class="distro-logo">
    {% endif %}
    <div>
        <h2>System Health Monitor</h2>
        <p>Comprehensive monitoring...</p>
    </div>
</div>

<div class="badge-showcase">
    {% if shields_badges.os %}
    <img src="{{ shields_badges.os }}" alt="OS Badge">
    {% endif %}
    <!-- More badges... -->
</div>
```

#### JavaScript Enhancements

```javascript
function updateBadges(badges, cpu, memory) {
    // Update CPU badge
    const cpuBadge = document.getElementById('cpu-badge');
    if (cpuBadge && badges.cpu) {
        cpuBadge.src = badges.cpu;
    }
    
    // Update memory badge
    const memoryBadge = document.getElementById('memory-badge');
    if (memoryBadge && badges.memory) {
        memoryBadge.src = badges.memory;
    }
    
    // Update uptime badge
    const uptimeBadge = document.getElementById('uptime-badge');
    if (uptimeBadge && badges.uptime) {
        uptimeBadge.src = badges.uptime;
    }
}
```

## File Organization

Per AGENTS.md guidelines:

- **Renamed:** `system_health_new.html` → `system_health_old.html`
- **Kept:** `system_health.html` (main active template)
- **Added:** Helper functions in `app_utils/system.py`
- **Documentation:** This file in `docs/`

## Testing

To test the changes:

1. Start the application:
   ```bash
   docker compose up -d --build
   ```

2. Navigate to the system health page:
   ```
   https://localhost/system_health
   ```

3. Verify:
   - [ ] Distribution logo appears in header
   - [ ] All badges display correctly
   - [ ] Badge colors reflect current metrics
   - [ ] Badges update when page refreshes
   - [ ] Hover effect on badges works

## Future Enhancements

Potential improvements:

1. **Additional Badges**
   - Network throughput badge
   - Disk I/O badge
   - Temperature badge
   - Container count badge

2. **More Distribution Logos**
   - Manjaro
   - Pop!_OS
   - Elementary OS
   - Gentoo

3. **Badge Customization**
   - User-configurable badge style (flat, flat-square, plastic, etc.)
   - Custom color schemes
   - Badge arrangement preferences

4. **Historical Trends**
   - Mini sparklines in badges
   - Click-to-expand with historical data

## References

- [Shields.io](https://shields.io/) - Badge generation service
- [Ubuntu Brand Assets](https://design.ubuntu.com/brand/ubuntu-logo/)
- [Debian Logos](https://www.debian.org/logos/)
- [AGENTS.md](../development/AGENTS.md) - Development guidelines
