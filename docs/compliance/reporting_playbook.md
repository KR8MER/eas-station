# Compliance Reporting Playbook

This playbook provides guidance for using the EAS Station's analytics and reporting capabilities to support regulatory compliance monitoring and operational excellence.

## Overview

The EAS Station analytics system provides comprehensive monitoring, trend analysis, and anomaly detection to help operators maintain compliance with FCC requirements and industry best practices. This playbook describes workflows for routine reporting, compliance verification, and incident investigation.

## Key Reporting Workflows

### 1. Weekly Test Verification (FCC Part 11.61(a)(1))

**Requirement**: Stations must conduct a weekly test of the EAS equipment at least once a week.

**Workflow**:

1. **Access Compliance Dashboard**
   - Navigate to `/eas/compliance` in the web interface
   - Review "Weekly Test Summary" section

2. **Verify Test Transmission**
   - Confirm that a Required Weekly Test (RWT) was transmitted within the past 7 days
   - Check that the test includes proper SAME header, attention signal, and audio message
   - Verify audio archive exists for the transmission

3. **Export Evidence**
   - Use "Export CSV" button to download weekly test log
   - Navigate to `/eas/audio-archive` to download audio recording
   - Print or save PDF report for station records

4. **Document Any Issues**
   - If test was missed, document reason in station log
   - If test quality is poor, investigate using analytics dashboard
   - Create corrective action plan if systematic issues are detected

**Automation**: The analytics scheduler automatically tracks weekly test compliance and flags missing tests as high-severity anomalies.

### 2. Monthly Test Verification (FCC Part 11.61(a)(1))

**Requirement**: Stations must participate in a state-level Required Monthly Test (RMT) or conduct equivalent testing.

**Workflow**:

1. **Access Alert Verification Page**
   - Navigate to `/eas/alert-verification`
   - Set time window to 35 days (to account for timing variations)

2. **Review Monthly Test Activity**
   - Filter alerts by event code "RMT" (Required Monthly Test)
   - Verify at least one RMT received and processed
   - Check originator codes match state emergency management authorities

3. **Analyze Test Quality**
   - Review "Trends by Originator" section for RMT sources
   - Check average confidence scores (should be ≥85%)
   - Identify any degraded audio quality trends

4. **Generate Compliance Report**
   - Export CSV with all RMT alerts for the month
   - Include audio archives for sample verification
   - Document any relayed/forwarded RMT transmissions

**Automation**: Monthly test compliance is tracked automatically, with alerts generated if no RMT is received within 35 days.

### 3. Alert Delivery Performance Monitoring

**Objective**: Track end-to-end alert delivery performance to ensure reliable emergency notification.

**Workflow**:

1. **Access Analytics Dashboard**
   - Navigate to `/analytics`
   - Review "Alert Delivery" metrics section

2. **Review Key Performance Indicators**
   - **Delivery Success Rate**: Should be ≥95%
   - **Average Delivery Latency**: Monitor for increasing trends
   - **Failed Delivery Count**: Investigate any non-zero values

3. **Analyze Trends**
   - Check 7-day and 30-day trend indicators
   - Look for declining success rates (falling trends)
   - Identify seasonal patterns or recurring issues

4. **Investigate Anomalies**
   - Review "Active Anomalies" section
   - Acknowledge anomalies after investigation
   - Document root cause and corrective actions

5. **API Access** (Optional)
   ```bash
   # Get alert delivery metrics for the last 7 days
   curl http://localhost:5000/api/analytics/metrics?category=alert_delivery&days=7

   # Get trend analysis
   curl http://localhost:5000/api/analytics/trends?category=alert_delivery&metric=delivery_success_rate
   ```

### 4. Audio Health Monitoring

**Objective**: Ensure audio capture and playout systems maintain signal integrity for reliable alert transmission.

**Workflow**:

1. **Access Analytics Dashboard**
   - Navigate to `/analytics`
   - Review "Audio Health" metrics section

2. **Monitor Health Scores**
   - **Average Audio Health Score**: Should be ≥80%
   - **Signal Quality Trends**: Monitor for degradation
   - **Source Availability**: Ensure backup sources are operational

3. **Investigate Quality Issues**
   - Navigate to `/settings/audio-sources` for real-time metering
   - Check peak and RMS levels for proper signal strength
   - Verify SDR receiver tuning and sensitivity settings

4. **Trending Analysis**
   - Review 30-day audio health trends
   - Correlate quality degradation with hardware changes
   - Plan preventive maintenance based on trends

5. **Anomaly Response**
   - **Spike Detection**: Sudden improvement may indicate upstream changes
   - **Drop Detection**: Sudden degradation requires immediate investigation
   - **Trend Break**: System-level changes detected, verify intentional

### 5. Receiver Status and Availability

**Objective**: Track uptime and reliability of EAS monitoring receivers.

**Workflow**:

1. **Access Statistics Dashboard**
   - Navigate to `/statistics`
   - Review "Receiver Performance" section

2. **Monitor Availability Metrics**
   - Check receiver uptime percentages (target: ≥99%)
   - Review alert reception counts by receiver
   - Identify receivers with degraded performance

3. **Analyze Multi-Receiver Correlation**
   - Compare alert counts across receivers
   - Investigate if one receiver consistently misses alerts
   - Verify geographic/frequency diversity is effective

4. **Maintenance Planning**
   - Use trend analysis to predict receiver failures
   - Schedule antenna maintenance during low-activity periods
   - Document receiver replacement decisions

### 6. GPIO Control and Relay Activation Auditing

**Objective**: Maintain audit trail of all transmitter control actions for regulatory compliance.

**Workflow**:

1. **Access Audit Logs**
   - Navigate to `/settings/security`
   - Review "Audit Log" section
   - Filter by category: "gpio_activation"

2. **Review Activation Records**
   - Verify all activations have documented operators
   - Check that activation durations match expected playout times
   - Investigate any failed activations

3. **Compliance Verification**
   - Correlate GPIO activations with alert records
   - Ensure all emergency alerts triggered transmitter control
   - Document manual overrides with justification

4. **Export for Record Keeping**
   - Export CSV of GPIO activation log
   - Retain records per station policy (typically 2+ years)
   - Include in annual compliance audits

### 7. Anomaly Investigation and Resolution

**Objective**: Respond to detected anomalies to maintain system reliability and compliance.

**Workflow**:

1. **Review Active Anomalies**
   - Navigate to `/analytics`
   - Check "Active Anomalies" section
   - Sort by severity (Critical → High → Medium → Low)

2. **Classify Anomaly Types**
   - **Outlier**: Single unusual data point, may be transient
   - **Spike**: Sudden increase, may indicate system improvement or misconfiguration
   - **Drop**: Sudden decrease, requires immediate attention
   - **Trend Break**: Long-term pattern change, verify intentional

3. **Investigation Steps**
   - Review metric details and baseline statistics
   - Check system logs for correlating events
   - Verify recent configuration or hardware changes
   - Test affected subsystems

4. **Document Resolution**
   - Acknowledge anomaly after investigation
   - Add resolution notes describing findings
   - Mark as "Resolved" once corrective action is complete
   - Flag as "False Positive" if anomaly was expected behavior

5. **API Workflow** (Optional)
   ```bash
   # Get active high-severity anomalies
   curl http://localhost:5000/api/analytics/anomalies?severity=high&active=true

   # Acknowledge anomaly
   curl -X POST http://localhost:5000/api/analytics/anomalies/123/acknowledge \
     -H "Content-Type: application/json" \
     -d '{"acknowledged_by": "operator_name", "notes": "Investigating..."}'

   # Resolve anomaly
   curl -X POST http://localhost:5000/api/analytics/anomalies/123/resolve \
     -H "Content-Type: application/json" \
     -d '{"resolved_by": "operator_name", "resolution_notes": "Fixed by restart"}'
   ```

### 8. Monthly Compliance Summary Report

**Objective**: Generate comprehensive monthly report for management and regulatory records.

**Workflow**:

1. **Collect Data Sources**
   - Weekly test verification records (4-5 per month)
   - Monthly test verification record (1 per month)
   - Alert delivery performance metrics
   - Audio health trend analysis
   - Receiver availability statistics
   - GPIO activation audit logs
   - Anomaly investigation records

2. **Generate Report Sections**

   **Executive Summary**:
   - Overall compliance status (compliant/non-compliant)
   - Key performance indicators
   - Critical anomalies and resolutions

   **Weekly Test Compliance**:
   - List all RWT transmissions with dates and times
   - Audio archive references
   - Any missed tests with explanations

   **Monthly Test Compliance**:
   - RMT reception and/or transmission details
   - State coordination notes
   - Audio quality assessment

   **System Performance**:
   - Alert delivery success rate and trends
   - Audio health scores and quality metrics
   - Receiver uptime and availability

   **Incident Summary**:
   - Anomalies detected and investigated
   - System outages and recovery actions
   - Maintenance activities performed

   **Corrective Actions**:
   - Issues identified and resolved
   - Preventive maintenance scheduled
   - System improvements implemented

3. **Export and Archive**
   - Export all data tables to CSV
   - Download sample audio archives
   - Save PDF reports from web interface
   - Store in compliance records per retention policy

4. **Review and Approval**
   - Station chief engineer review
   - General manager approval
   - File in station public inspection file if required

### 9. Annual FCC Compliance Audit

**Objective**: Prepare for annual regulatory compliance verification.

**Workflow**:

1. **Pre-Audit Preparation**
   - Collect 12 months of monthly compliance reports
   - Verify weekly and monthly test documentation is complete
   - Review all anomaly investigations for completeness
   - Ensure audio archives are accessible and playable

2. **Documentation Assembly**
   - Equipment inventory and specifications
   - Configuration baseline and change log
   - Training records for operators
   - Security access logs (MFA, role changes)
   - System backup and recovery test results

3. **Compliance Verification**
   - Calculate weekly test completion rate (should be ≥52 per year)
   - Verify monthly test participation (12 per year)
   - Review alert delivery performance trends
   - Document any non-compliance with corrective actions

4. **Regulatory Submission** (if required)
   - Prepare Form 2000 series submissions
   - Include EAS Equipment Log (FCC Form 2000E)
   - Attach compliance documentation as required
   - Retain proof of submission

### 10. Troubleshooting and Diagnostic Workflows

**Common Issues and Resolution Steps**:

#### Missing Weekly/Monthly Tests

**Symptoms**: Analytics dashboard shows "Compliance Gap" or missing test anomaly

**Investigation**:
1. Check receiver status - are all receivers operational?
2. Verify network connectivity - can IPAWS feed be reached?
3. Review alert history - are other alerts being received?
4. Check audio sources - is audio capture working?

**Resolution**:
- If receiver failure: restart receiver service, check antenna/RF connections
- If network issue: verify firewall rules, check upstream connectivity
- If isolated incident: manually generate test using Manual Broadcast Builder
- If systematic: investigate configuration and hardware

#### Poor Audio Quality

**Symptoms**: Low confidence scores, anomalies in audio health metrics

**Investigation**:
1. Navigate to `/settings/audio-sources` for real-time metering
2. Check signal levels - should be -20dBFS to -6dBFS peak
3. Review audio source priorities and failover configuration
4. Test with known-good audio sample

**Resolution**:
- Adjust input gain/attenuation on capture device
- Re-tune SDR receiver for better signal quality
- Switch to backup audio source
- Replace failing hardware (sound card, SDR, antenna)

#### High Alert Delivery Latency

**Symptoms**: Increasing trend in delivery latency metric

**Investigation**:
1. Check system resource utilization (CPU, memory, disk)
2. Review database performance - are queries slow?
3. Verify network latency to alert sources
4. Check for background processing contention

**Resolution**:
- Optimize database indices (run VACUUM/ANALYZE)
- Increase system resources (RAM, CPU)
- Adjust analytics scheduler intervals to reduce load
- Investigate and resolve database query bottlenecks

#### False Positive Anomalies

**Symptoms**: Repeated anomaly detections for expected behavior

**Investigation**:
1. Review anomaly details - what triggered detection?
2. Check if system configuration changed intentionally
3. Verify if operational patterns changed (e.g., increased test frequency)
4. Review baseline statistics - may need adjustment

**Resolution**:
- Mark anomalies as "False Positive" to exclude from active list
- Consider adjusting anomaly detection sensitivity thresholds
- Document expected operational pattern change
- Update baseline after significant system changes

## Automated Reporting Configuration

The analytics scheduler runs automatically in the background and can be configured via environment variables or the Flask application configuration.

### Scheduler Configuration

Default intervals:
- **Metrics Aggregation**: Every 60 minutes
- **Trend Analysis**: Every 6 hours (360 minutes)
- **Anomaly Detection**: Every 60 minutes

To adjust intervals, modify `webapp/__init__.py` or set environment variables:

```python
from app_core.analytics import start_scheduler

# Custom intervals (in minutes)
start_scheduler(
    metrics_interval_minutes=30,     # Aggregate metrics every 30 minutes
    trends_interval_minutes=180,     # Analyze trends every 3 hours
    anomalies_interval_minutes=60,   # Detect anomalies every hour
)
```

### Manual Triggering

To manually run analytics tasks (useful for testing or on-demand reports):

```bash
# Via API
curl -X POST http://localhost:5000/api/analytics/metrics/aggregate
curl -X POST http://localhost:5000/api/analytics/trends/analyze
curl -X POST http://localhost:5000/api/analytics/anomalies/detect

# Via Python console
from app_core.analytics import get_scheduler
scheduler = get_scheduler()
scheduler.run_now("all")  # Run all tasks immediately
```

## Best Practices

1. **Regular Review**: Check analytics dashboard daily, investigate anomalies weekly
2. **Documentation**: Document all anomaly investigations and resolutions
3. **Trend Monitoring**: Watch for gradual degradation trends before they become critical
4. **Preventive Maintenance**: Use trend forecasts to plan hardware maintenance
5. **Audit Trail**: Maintain compliance records for minimum 2 years (or per local requirements)
6. **Access Control**: Use RBAC to restrict analytics management to authorized operators
7. **Data Retention**: Configure database retention policies to balance storage and historical analysis
8. **Backup Verification**: Include analytics data in regular backup procedures
9. **Training**: Ensure all operators understand how to access and interpret reports
10. **Continuous Improvement**: Review and refine thresholds based on operational experience

## Compliance References

- **FCC Part 11.61(a)(1)**: EAS weekly test requirements
- **FCC Part 11.61(a)(2)**: EAS required monthly test requirements
- **FCC Part 11.35**: EAS equipment operational requirements
- **FCC Part 11.52**: EAS header and message requirements
- **FCC Part 11.54**: Attention signal specifications

## Support and Resources

- Analytics Module Documentation: `app_core/analytics/README.md`
- API Endpoint Reference: See `/api/analytics/*` routes in `webapp/routes_analytics.py`
- Database Schema: `app_core/analytics/models.py`
- Web Interface: `/analytics` dashboard
- Compliance Dashboard: `/eas/compliance`
- Alert Verification: `/eas/alert-verification`

## Maintenance and Updates

This playbook should be reviewed and updated:
- After major system upgrades
- When FCC regulations change
- After operational process improvements
- At least annually as part of compliance audit

Last Updated: 2025-11-05
