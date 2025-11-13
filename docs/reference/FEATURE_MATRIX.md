# Feature Coverage Matrix

A high-level index of major EAS Station capabilities, where they live in the UI, and where to find deeper documentation. Use this matrix to verify that every feature ships with discoverable docs.

| Feature | What It Does | Where to Access | Documentation | Notes |
|---------|---------------|-----------------|---------------|-------|
| Multi-source alert ingestion | Poll NOAA Weather Radio, IPAWS, and custom CAP feeds, then normalize alerts | **Monitoring → Alerts History** | [docs/guides/HELP.md](../guides/HELP#monitoring-live-alerts), [docs/architecture/THEORY_OF_OPERATION.md](../architecture/THEORY_OF_OPERATION#1-ingestion-validation) | Includes feed configuration walkthroughs |
| Broadcast operations workflow | Review, approve, and transmit SAME alerts with compliance logging | **Broadcast Operations** menu | [docs/architecture/THEORY_OF_OPERATION.md](../architecture/THEORY_OF_OPERATION#4-broadcast-orchestration), [docs/guides/HELP.md](../guides/HELP#reviewing-compliance-weekly-tests) | UI screenshots pending refresh |
| Audio monitoring dashboard | Stream live audio, inspect levels, and confirm ingest health | **Monitoring → Audio Monitoring** | [docs/audio/AUDIO_MONITORING.md](../audio/AUDIO_MONITORING) | Links from ICECAST/IHeart guides updated |
| System log explorer | Filter system, polling, audio, and GPIO logs in real time | **System → System Logs** | [docs/guides/HELP.md](../guides/HELP#troubleshooting), [docs/guides/HELP.md](../guides/HELP#reference-commands) | Need screenshot update after UI refresh |
| GPIO relay control | Map alerts to physical relays and review activation history | **Configuration → GPIO Control** | [docs/hardware/gpio.md](../hardware/gpio#configuration) | Hardware diagram verified |
| LED/VFD signage | Push alert text to LED ticker and VFD displays | **Configuration → Displays** | [docs/guides/CUSTOM_DISPLAY_SCREENS.md](../guides/CUSTOM_DISPLAY_SCREENS), [docs/deployment/post_install.md](../deployment/post_install#led-sign-optional) | Requires operator setup steps |
| Notification channels | Email/SMS notifications with templated messaging | **Configuration → Notifications** | [docs/deployment/post_install.md](../deployment/post_install#email-notifications-optional), [docs/frontend/JAVASCRIPT_API.md](../frontend/JAVASCRIPT_API#notifications-easnotifications) | Document webhook integrations next |
| Portainer deployment | One-click stack install/upgrade for Docker environments | N/A (external) | [docs/deployment/portainer/PORTAINER_QUICK_START.md](../deployment/portainer/PORTAINER_QUICK_START), [docs/guides/PORTAINER_DEPLOYMENT.md](../guides/PORTAINER_DEPLOYMENT) | Combine with network/database runbooks |
| Setup wizard & environment config | First-run configuration, environment validation, `.env` migration | **Configuration → Environment** | [docs/guides/SETUP_INSTRUCTIONS.md](../guides/SETUP_INSTRUCTIONS#core-configuration), [docs/guides/SETUP_INSTRUCTIONS.md](../guides/SETUP_INSTRUCTIONS#hardware-integration) | Needs troubleshooting FAQ |
| API & integrations | REST/JSON APIs for automating alerts and ingest | `/api/*` | [docs/frontend/JAVASCRIPT_API.md](../frontend/JAVASCRIPT_API#api-client-easapi), [README.md](https://github.com/KR8MER/eas-station/blob/main/README.md#-api-endpoints) | Expand with authenticated examples |

## Coverage Gaps

- 🔄 **Troubleshooting Guide** – still tracked in `docs/documentation_audit.md`
- 🖼️ **Screenshots** – update `/help` screenshots after UI refresh
- 🔌 **Webhooks** – document outgoing webhook support once finalized

Maintainers: update this matrix whenever a new feature ships or a feature gains substantial documentation.
