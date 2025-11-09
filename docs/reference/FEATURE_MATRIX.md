# Feature Coverage Matrix

A high-level index of major EAS Station capabilities, where they live in the UI, and where to find deeper documentation. Use this matrix to verify that every feature ships with discoverable docs.

| Feature | What It Does | Where to Access | Documentation | Notes |
|---------|---------------|-----------------|---------------|-------|
| Multi-source alert ingestion | Poll NOAA Weather Radio, IPAWS, and custom CAP feeds, then normalize alerts | **Monitoring → Alerts History** | [docs/guides/HELP.md](../guides/HELP.md#alert-monitoring) | Includes feed configuration walkthroughs |
| Broadcast operations workflow | Review, approve, and transmit SAME alerts with compliance logging | **Broadcast Operations** menu | [docs/architecture/THEORY_OF_OPERATION.md](../architecture/THEORY_OF_OPERATION.md#broadcast-pipeline), [docs/guides/HELP.md](../guides/HELP.md#broadcast-operations) | UI screenshots pending refresh |
| Audio monitoring dashboard | Stream live audio, inspect levels, and confirm ingest health | **Monitoring → Audio Monitoring** | [docs/audio/AUDIO_MONITORING.md](../audio/AUDIO_MONITORING.md) | Links from ICECAST/IHeart guides updated |
| System log explorer | Filter system, polling, audio, and GPIO logs in real time | **System → System Logs** | [docs/guides/HELP.md](../guides/HELP.md#system-logs), [docs/reference/CHANGELOG.md](CHANGELOG.md#log-viewer) | Need screenshot update after UI refresh |
| GPIO relay control | Map alerts to physical relays and review activation history | **Configuration → GPIO Control** | [docs/hardware/GPIO_RELAY_WIRING.md](../hardware/GPIO_RELAY_WIRING.md), [docs/guides/HELP.md](../guides/HELP.md#gpio-control) | Hardware diagram verified |
| LED/VFD signage | Push alert text to LED ticker and VFD displays | **Configuration → Displays** | [docs/hardware/LED_DISPLAY_GUIDE.md](../hardware/LED_DISPLAY_GUIDE.md), [docs/hardware/VFD_GUIDE.md](../hardware/VFD_GUIDE.md) | Requires operator setup steps |
| Notification channels | Email/SMS notifications with templated messaging | **Configuration → Notifications** | [docs/guides/HELP.md](../guides/HELP.md#notifications), [docs/reference/ABOUT.md](ABOUT.md#notifications) | Document webhook integrations next |
| Portainer deployment | One-click stack install/upgrade for Docker environments | N/A (external) | [docs/deployment/portainer/PORTAINER_QUICK_START.md](../deployment/portainer/PORTAINER_QUICK_START.md), [docs/guides/PORTAINER_DEPLOYMENT.md](../guides/PORTAINER_DEPLOYMENT.md) | Combine with network/database runbooks |
| Setup wizard & environment config | First-run configuration, environment validation, `.env` migration | **Configuration → Environment** | [docs/guides/SETUP_INSTRUCTIONS.md](../guides/SETUP_INSTRUCTIONS.md), [docs/reference/ABOUT.md](ABOUT.md#configuration) | Needs troubleshooting FAQ |
| API & integrations | REST/JSON APIs for automating alerts and ingest | `/api/*` | [docs/frontend/JAVASCRIPT_API.md](../frontend/JAVASCRIPT_API.md), [README.md](../../README.md#-api-endpoints) | Expand with authenticated examples |

## Coverage Gaps

- 🔄 **Troubleshooting Guide** – still tracked in `docs/documentation_audit.md`
- 🖼️ **Screenshots** – update `/help` screenshots after UI refresh
- 🔌 **Webhooks** – document outgoing webhook support once finalized

Maintainers: update this matrix whenever a new feature ships or a feature gains substantial documentation.
