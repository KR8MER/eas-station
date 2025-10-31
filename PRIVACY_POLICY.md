# 🛡️ Privacy Policy

_Last updated: January 15, 2025_

EAS Station is a self-hosted project that runs entirely under your control. The maintainers do not operate a hosted service, collect analytics, or receive telemetry from deployments. This policy explains how to handle data while testing the software in lab environments.

## 1. Project Scope
- The maintainers do not collect or process any information from your installations.
- All data stored by the application resides within the infrastructure you provision (databases, volumes, backups).

## 2. Local Data Storage
- The system may store configuration details, receiver metadata, CAP alert content, generated audio, and system logs.
- These records exist to support testing workflows only. Remove sample data before reusing hardware or sharing backups.
- Treat any stored alert content as non-authoritative until validated on certified FCC equipment.

## 3. Optional Integrations
- If you enable third-party services (e.g., Azure Speech, SMTP relays, mapping APIs) their respective privacy policies apply.
- Configure credentials via environment variables and avoid transmitting sensitive or personally identifiable information through optional integrations.

## 4. Development & Testing Data
- Populate EAS Station exclusively with non-production or simulated data while it remains in development.
- Do not ingest live IPAWS traffic, dispatch records, or emergency response telemetry.
- The maintainers are not responsible for safeguarding any datasets you choose to import.

## 5. Security Practices
- Restrict access to the application behind VPNs or private networks.
- Rotate credentials regularly and store secrets outside of source control.
- Apply dependency and OS security updates before inviting additional testers.
- Disconnect experimental builds from broadcast chains, transmitter controls, or other life-safety infrastructure.

## 6. No Data Warranty
- The maintainers disclaim all responsibility for data loss, corruption, disclosure, or regulatory issues arising from use of the software.
- You are solely responsible for implementing appropriate backups and safeguards.

## 7. Contact
- Submit privacy-related questions through the GitHub issue tracker.
- Do **not** send sensitive personal data, emergency requests, or proprietary information through that channel.
