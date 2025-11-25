# Cellular HAT Evaluation for EAS Station

**Created:** 2025-11-20
**Status:** Planning / Evaluation Phase
**Target:** Raspberry Pi 5 Deployment

## Executive Summary

This document evaluates adding cellular connectivity to EAS Station via LTE/4G/5G HAT modules. Based on codebase analysis and market research, **cellular support would provide significant value** for remote deployments and network redundancy scenarios.

### Quick Recommendation

**Recommended HAT Options (Ranked by Value):**

1. **Waveshare SIM7600G-H** - $76, best value for most users
2. **Sixfab 4G/LTE Base HAT** - $109, easier setup, better ecosystem
3. **Waveshare 5G HAT+ (RM520N-GL)** - $260+, for future-proofing

**Skip cellular if:**
- You have reliable wired internet with UPS backup
- Budget is very tight (<$100 available)
- Site has zero cellular signal
- You don't need remote deployment capability

---

## Current Network Architecture

### How EAS Station Uses Network Connectivity

EAS Station requires continuous internet access for:

| Service | Bandwidth | Frequency | Failure Impact |
|---------|-----------|-----------|----------------|
| **NOAA CAP Polling** | ~50 KB/request | Every 3 minutes | Missing weather alerts |
| **IPAWS Polling** | ~50 KB/request | Every 3 minutes | Missing federal alerts |
| **Database Sync** | Minimal | Continuous | Data loss risk |
| **Web Dashboard** | Variable | On-demand | Admin access lost |
| **Icecast Streaming** | 128-320 kbps | Continuous (optional) | Audio monitoring lost |
| **NTP Time Sync** | <1 KB | Every hour | Timestamp drift |

**Estimated Total Data Usage:**
- Core operations: **5-10 MB/day**
- With Icecast streaming: **1-3 GB/day** (24/7 at 128 kbps)
- Emergency operations only: **2-3 MB/day**

### Current Failover Capability

From `docs/runbooks/outage_response.md` analysis:

**Manual Standby Activation:** ✅ Documented
**Automatic Failover:** ❌ Not implemented
**Network Redundancy:** ❌ Single network path
**Connection Monitoring:** ✅ Health checks available

**Gap:** No automatic network failover when primary internet fails.

---

## Cellular HAT Comparison Matrix

### Feature Comparison

| Feature | Waveshare SIM7600G-H | Sixfab 4G Base HAT | Waveshare 5G HAT+ |
|---------|---------------------|-------------------|------------------|
| **Price** | $76 | $109 + modem | $260-338 |
| **Speed (Down)** | 150 Mbps (LTE Cat-4) | 150 Mbps (LTE Cat-4) | 2.5 Gbps (5G) |
| **Pi 5 Support** | ✅ Via GPIO | ✅ Via GPIO | ✅ Via PCIe |
| **GNSS/GPS** | ✅ GPS/GLONASS/Galileo | ⚠️ Depends on modem | ✅ Most modules |
| **Onboard Audio** | ✅ (for voice calls) | ❌ | ❌ |
| **SIM Card Slot** | ✅ Standard/Nano | ✅ Standard | ✅ Standard |
| **Power** | 5V via GPIO (2A peak) | 5V via GPIO | 5V + barrel jack |
| **Antennas** | 2 (LTE + GPS) | 2-4 (depends on kit) | 4 (included) |
| **AT Commands** | ✅ Via USB/UART | ✅ Via USB | ✅ Via USB |
| **Ecosystem** | Good docs, China-based | Excellent, NA support | Good docs |
| **Setup Difficulty** | Medium | Easy (managed service) | Medium-Hard |

### Regional Compatibility

**Waveshare SIM7600G-H (Global):**
- North America: ✅ (AT&T, T-Mobile, Verizon)
- Europe: ✅ (most carriers)
- Asia: ✅ (most carriers)
- Bands: B1/B2/B3/B4/B5/B7/B8/B12/B13/B18/B19/B20/B25/B26/B28/B66

**Sixfab Modules:**
- Region-specific variants available (check before purchase)
- Some modules are carrier-locked (e.g., Verizon-only)

**Waveshare 5G HAT+:**
- Check specific module SKU for regional support
- RM520N-GL: Global multi-band 5G Sub-6GHz

---

## Use Cases for EAS Station

### 1. Network Redundancy (Primary Use Case)

**Problem:** Internet outage = no alert monitoring

**Solution:** Automatic failover ethernet → WiFi → cellular

**Implementation Complexity:** Medium
**Value:** ⭐⭐⭐⭐⭐ **Critical for 24/7 operations**

**Example Scenario:**
```
12:00 AM - Storm damages fiber line to site
12:01 AM - EAS Station detects ethernet down
12:01 AM - Automatically switches to cellular backup
12:02 AM - Continues receiving tornado warnings via LTE
12:02 AM - SMS alert sent to admin: "Failover to cellular"
08:00 AM - Fiber repaired, switches back to ethernet
```

### 2. Remote Site Deployment

**Problem:** No wired internet at remote locations

**Solution:** Cellular as primary connection

**Sites that benefit:**
- Mountaintop repeater sites
- Rural fire stations
- Mobile command vehicles
- Emergency shelters
- Amateur radio field day setups

**Implementation Complexity:** Low
**Value:** ⭐⭐⭐⭐⭐ **Essential for remote deployments**

### 3. GPS Time Synchronization

**Problem:** NTP requires internet; clock drift during outages

**Solution:** GNSS provides accurate time without internet

**Benefits:**
- Sub-second accuracy (vs ±seconds with NTP)
- Works during internet outages
- FCC compliance for alert timestamps
- Broadcast timing accuracy

**Implementation Complexity:** Low
**Value:** ⭐⭐⭐⭐ **Valuable for compliance**

### 4. SMS Alerting

**Problem:** Critical alerts may not be seen during off-hours

**Solution:** SMS notifications to operators

**Example Alerts:**
- "TORNADO WARNING active for your county"
- "Database connection lost"
- "System switched to cellular backup"
- "Backup failed - manual intervention required"

**Implementation Complexity:** Medium
**Value:** ⭐⭐⭐⭐ **High value for unmanned sites**

### 5. Location Verification

**Problem:** Equipment moved without config update

**Solution:** GPS verifies configured FIPS codes match actual location

**Use Cases:**
- Mobile deployments (verify location before broadcasts)
- Anti-theft detection
- Automatic county/zone updates when relocating

**Implementation Complexity:** Medium
**Value:** ⭐⭐⭐ **Nice-to-have for mobile units**

---

## Technical Implementation Plan

### Phase 1: Hardware Detection and Basic Connectivity

**Goal:** Detect HAT, establish PPP/QMI connection, verify data flow

**Components:**
- ModemManager integration
- PPP/QMI connection scripts
- AT command interface
- Signal strength monitoring
- Data usage tracking

**Effort:** 2-3 days development + testing

**Files to Create/Modify:**
```
app_core/cellular/
├── __init__.py
├── modem_manager.py      # Detect and initialize modem
├── connection.py         # PPP/QMI setup and management
├── signal_monitor.py     # Signal strength, carrier info
└── data_usage.py         # Track cellular data consumption

scripts/
└── cellular_setup.sh     # Install dependencies (ModemManager, etc)

docker-compose.cellular.yml  # Docker overlay for cellular support
```

### Phase 2: Network Failover

**Goal:** Automatic switching between ethernet → WiFi → cellular

**Logic:**
```python
# Network priority
1. Ethernet (if available)
2. WiFi (if configured and available)
3. Cellular (always available as backup)

# Health check loop (every 30 seconds)
if not can_reach_internet(primary_interface):
    log_failover_event()
    switch_to_next_interface()
    send_notification(admin_contacts)
```

**Effort:** 2 days development + testing

**Files to Create:**
```
app_core/network/
├── __init__.py
├── failover.py           # Connection health checks and switching
└── interface_manager.py  # Manage routing tables

webapp/routes_network.py  # Dashboard for network status
```

### Phase 3: GPS Integration

**Goal:** Parse GNSS data, sync system time, verify location

**Components:**
- gpsd integration
- NMEA sentence parsing
- Chrony/timesyncd configuration for GPS PPS
- FIPS code location verification

**Effort:** 1-2 days development + testing

**Files to Create:**
```
app_core/gps/
├── __init__.py
├── nmea_parser.py        # Parse GPS sentences
├── time_sync.py          # Sync system clock to GPS
└── location_verify.py    # Compare GPS coords to configured FIPS

scripts/
└── gps_time_setup.sh     # Configure chrony for GPS time source
```

### Phase 4: SMS Notifications

**Goal:** Send SMS alerts for critical events

**Components:**
- AT command SMS interface
- Notification rules engine
- SMS command parser (for remote status queries)

**Effort:** 2 days development + testing

**Files to Create:**
```
app_core/cellular/
├── sms.py                # Send/receive SMS via AT commands
└── notifications.py      # SMS notification rules

webapp/routes_notifications.py  # Configure SMS alerts
```

### Phase 5: Dashboard Integration

**Goal:** Web UI for cellular status and configuration

**Features:**
- Real-time signal strength indicator
- Current carrier and connection type (4G/LTE/5G)
- Data usage charts (daily/monthly)
- GPS coordinates and satellite count
- Network failover status and history
- SMS notification configuration

**Effort:** 2-3 days development + testing

**Files to Modify:**
```
webapp/admin/dashboard.py         # Add cellular stats widget
webapp/routes_settings_network.py # Cellular configuration page
templates/admin/dashboard.html    # Add cellular status panel
templates/settings/network.html   # Cellular config form
```

---

## Cost-Benefit Analysis

### One-Time Costs

| Item | Waveshare SIM7600 | Sixfab 4G HAT | Waveshare 5G HAT+ |
|------|------------------|---------------|-------------------|
| HAT Hardware | $76 | $109 + $40-80 modem | $260-338 |
| Antennas | Included | Included | Included |
| SIM Card | $5-25 | $5-25 | $5-25 |
| **Total** | **$81-101** | **$154-214** | **$285-363** |

### Recurring Costs (Monthly)

| Provider | Data Allowance | Cost | Suitable For |
|----------|---------------|------|--------------|
| **Twilio Super SIM** | Pay-as-you-go | $0.10/MB | Dev/testing |
| **Hologram IoT** | 1 GB | $10/month | Light usage |
| **Ting Mobile** | 1 GB | $8/month | Light usage |
| **T-Mobile IoT** | 5 GB | $20/month | Production use |
| **AT&T IoT** | Unlimited | $25/month | Heavy streaming |

**Recommended for EAS Station:** $10-20/month tier (1-5 GB)

### Cost Comparison to Alternative Solutions

| Solution | One-Time | Monthly | Pros | Cons |
|----------|----------|---------|------|------|
| **Cellular HAT** | $81-363 | $10-20 | Integrated, automatic | Hardware cost |
| **USB LTE Modem** | $50-100 | $10-20 | Cheaper, portable | Less integrated |
| **Cellular Router** | $200-500 | $40-60 | Enterprise-grade | Expensive, overkill |
| **Redundant ISP** | $0-200 | $50-100 | High bandwidth | Costly, both may fail in disaster |
| **Satellite** | $500-2000 | $100-200 | True backup | Very expensive, high latency |

**Winner for EAS Station:** Cellular HAT (best balance of cost, integration, reliability)

### Return on Investment

**Scenario 1: Prevent One Missed Tornado Warning**

If cellular backup prevents missing ONE tornado warning during an internet outage:
- Cost of HAT: $100
- Monthly service: $15
- **Payback period:** Immediate (public safety value is priceless)

**Scenario 2: Enable Remote Site Deployment**

Deploy to remote fire station with no wired internet:
- Alternative: Run fiber/cable to site = $5,000-50,000
- Cellular solution: $100 hardware + $15/month
- **Payback period:** First month

**Scenario 3: FCC Compliance Improvement**

GPS time sync for accurate timestamps:
- Cost: $0 (included with HAT)
- Benefit: Better compliance documentation, reduced audit risk

---

## Integration Complexity Assessment

### What Changes Are Needed?

**Minimal Impact Areas:** ✅
- Alert polling (already uses HTTP, works over any interface)
- Database (already container-networked)
- Web dashboard (already accessible)

**Moderate Changes Needed:** ⚠️
- Docker networking (add cellular interface passthrough)
- Time synchronization (add gpsd support)
- Health monitoring (add cellular metrics)

**New Components Required:** 🆕
- ModemManager/NetworkManager packages
- gpsd for GPS parsing
- Failover logic and monitoring
- SMS interface library

### Docker Integration

Add to `docker-compose.cellular.yml`:

```yaml
services:
  app:
    devices:
      - /dev/ttyUSB0:/dev/ttyUSB0  # Modem control
      - /dev/ttyUSB1:/dev/ttyUSB1  # Modem GPS
      - /dev/ttyUSB2:/dev/ttyUSB2  # Modem data
    cap_add:
      - NET_ADMIN              # For network management
    volumes:
      - /var/run/dbus:/var/run/dbus:ro  # For ModemManager

  cellular-manager:
    image: eas-station:latest
    command: python app_core/cellular/manager.py
    devices:
      - /dev/ttyUSB0:/dev/ttyUSB0
      - /dev/ttyUSB1:/dev/ttyUSB1
      - /dev/ttyUSB2:/dev/ttyUSB2
    network_mode: host  # Required for PPP interface
    cap_add:
      - NET_ADMIN
    privileged: true
```

**Complexity Rating:** Medium (requires privileged containers for network management)

---

## Risks and Limitations

### Technical Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Carrier compatibility issues | Medium | Test with target carrier before deployment |
| Data cap overruns | Low | Implement usage monitoring and alerts |
| Signal issues in building | Medium | External antenna mounting |
| USB device passthrough in Docker | Low | Well-documented, tested pattern |
| Modem firmware bugs | Low | Use proven modules (SIM7600) |
| Power consumption | Low | HAT draws ~500mA, within Pi 5 limits |

### Operational Considerations

**Good:**
- Simple SIM card replacement
- Remote management via SSH
- Standard AT commands
- Automatic reconnection

**Challenges:**
- Need to configure APN for carrier
- Some carriers require device registration
- Antenna placement for best signal
- Testing requires actual SIM card and coverage

### Known Limitations

**What Cellular CANNOT Do:**
- Replace wired internet for high-bandwidth needs (Icecast 320kbps streams = 1 GB/day)
- Work in areas with zero cellular coverage (check coverage maps first)
- Provide millisecond-level latency for real-time applications
- Bypass carrier data caps (choose appropriate plan)

**What Cellular DOES WELL:**
- Reliable backup for text-based protocols (CAP XML polling)
- SMS alerting without internet
- GPS time sync without network
- Remote site connectivity

---

## Vendor Comparison Deep Dive

### Waveshare SIM7600G-H - Recommended for Most Users

**Strengths:**
- ✅ All-in-one solution (modem + GPS + audio codec)
- ✅ Best documentation (detailed wiki)
- ✅ Proven reliability (widely deployed)
- ✅ Lowest cost ($76)
- ✅ Standard AT commands
- ✅ Direct USB to serial drivers

**Weaknesses:**
- ⚠️ China-based vendor (slower support)
- ⚠️ Antennas are adequate but not premium

**Best For:** Standard deployments, budget-conscious projects

### Sixfab 4G/LTE Base HAT - Best for Beginners

**Strengths:**
- ✅ Excellent North American support
- ✅ Managed SIM card service (Super SIM integration)
- ✅ Better ecosystem (compatible modems, accessories)
- ✅ Active community forum
- ✅ Comprehensive tutorials

**Weaknesses:**
- ❌ Higher cost ($109 + modem)
- ❌ Requires separate modem purchase
- ⚠️ Some modems are carrier-locked

**Best For:** Commercial deployments, users wanting support

### Waveshare 5G HAT+ - Future-Proofing

**Strengths:**
- ✅ 5G speeds (when available)
- ✅ PCIe interface (better performance)
- ✅ Premium build quality
- ✅ Multiple module options

**Weaknesses:**
- ❌ Expensive ($260-338)
- ❌ Requires Pi 5 (no backward compatibility)
- ❌ Higher power consumption
- ⚠️ 5G coverage still limited in many areas

**Best For:** High-bandwidth needs, future-proofing investments

---

## Recommendation Matrix

### Choose Waveshare SIM7600G-H If:

- ✅ Budget is primary concern
- ✅ Deploying 1-5 units
- ✅ You're comfortable with Linux and AT commands
- ✅ Standard 4G LTE speeds are sufficient
- ✅ You need GPS time sync
- ✅ Remote site has decent LTE coverage

**Confidence Level:** High - Proven solution, widely used

### Choose Sixfab If:

- ✅ Budget allows extra $50-100/unit
- ✅ You want easier setup and better support
- ✅ Deploying 10+ units (enterprise use)
- ✅ You may need to swap modems/carriers
- ✅ You value North American support

**Confidence Level:** High - Professional ecosystem

### Choose Waveshare 5G HAT+ If:

- ✅ Site has 5G coverage
- ✅ You need higher bandwidth (multi-stream Icecast)
- ✅ Budget allows $300+/unit
- ✅ Only using Pi 5 (no older models)
- ✅ Future-proofing is important

**Confidence Level:** Medium - Newer technology, less proven

### Skip Cellular If:

- ❌ Site has zero cellular coverage
- ❌ Budget is very limited (<$100 available)
- ❌ You have reliable wired internet + UPS + redundant ISP
- ❌ Site is manned 24/7 (can manually switch to backup)
- ❌ Alert delays of hours are acceptable

---

## Next Steps

### If You Decide to Proceed

**Phase 1: Research (1 week)**
- [ ] Check cellular coverage at deployment site (use carrier maps)
- [ ] Determine which carrier has best coverage in your area
- [ ] Decide on HAT model (recommend Waveshare SIM7600G-H)
- [ ] Select data plan (recommend Hologram or Ting for testing)

**Phase 2: Purchase and Test (1-2 weeks)**
- [ ] Order HAT and antennas
- [ ] Order SIM card (get activated)
- [ ] Test HAT on bench with test SIM
- [ ] Verify data connection and GPS lock
- [ ] Measure data usage with CAP polling

**Phase 3: Software Integration (2-3 weeks)**
- [ ] Implement hardware detection
- [ ] Add basic PPP/QMI connectivity
- [ ] Create dashboard widgets
- [ ] Add GPS time sync
- [ ] Implement SMS notifications

**Phase 4: Deployment (1 week)**
- [ ] Test failover in lab environment
- [ ] Document configuration steps
- [ ] Deploy to production site
- [ ] Monitor for 1 week
- [ ] Tune signal/placement if needed

**Total Timeline:** 5-7 weeks from decision to production

### If You Decide to Wait

**Alternative Solutions:**
1. **USB LTE Modem** - Lower cost, less integrated (~$50)
2. **WiFi Failover** - If site has multiple WiFi networks (no cost)
3. **Manual Standby Node** - Already documented in outage runbook (no cost)
4. **Redundant ISP** - Second internet provider ($50-100/month)

**Revisit Decision When:**
- You have a specific remote deployment need
- Internet outages become frequent (>1/month)
- FCC compliance requires better time sync
- Budget allows hardware investment

---

## Questions to Consider

Before making a decision, consider:

1. **How often does your site lose internet?**
   - Never: Cellular is nice-to-have
   - Monthly: Cellular is valuable
   - Weekly: Cellular is essential

2. **What's the cost of missing an alert?**
   - Low impact: May not justify cost
   - Public safety critical: Absolutely justify cost

3. **Is your deployment remote/mobile?**
   - Fixed site with wired internet: Lower priority
   - Remote/mobile: Essential

4. **Do you need GPS time sync?**
   - Just for accuracy: Nice-to-have
   - FCC compliance critical: High value

5. **What's your budget?**
   - <$100: Consider cheaper alternatives
   - $100-200: Perfect for cellular HAT
   - $200+: Consider premium options or multiple backups

---

## References

- [Waveshare SIM7600G-H Wiki](https://www.waveshare.com/wiki/SIM7600E-H_4G_HAT)
- [Sixfab Documentation](https://docs.sixfab.com/)
- [ModemManager Project](https://www.freedesktop.org/wiki/Software/ModemManager/)
- [gpsd Documentation](https://gpsd.gitlab.io/gpsd/)
- [AT Commands Reference (3GPP)](https://www.3gpp.org/)

---

**Document Maintainer:** Claude (AI Assistant)
**Review Status:** Draft - Awaiting User Feedback
**Next Review:** After hardware selection decision
