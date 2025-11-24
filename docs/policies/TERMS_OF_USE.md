# ⚖️ Terms of Use

_Last updated: January 30, 2025_

> **Critical Safety Notice:** EAS Station is experimental software. It must not be used for life-safety, mission-critical, or FCC-mandated alerting. Commercially certified EAS equipment remains the only acceptable solution for regulatory compliance.

## 1. Project Status & Intended Use
- EAS Station is a community-driven development project currently in a pre-production, experimental phase with a roadmap focused on matching the functionality of commercial encoder/decoder hardware using off-the-shelf components.
- The reference build now leverages Raspberry Pi 5 compute modules (4 GB RAM baseline) paired with GPIO relay HATs, RS-232 interfaces, SDR receivers, and broadcast-grade audio cards. Raspberry Pi 4 hardware remains compatible for lab work, but it is no longer the documented baseline. None of these components are an approved substitute for certified encoder/decoder equipment until the software attains formal authorization.
- The codebase has been cross-checked against open-source utilities such as [multimon-ng](https://github.com/EliasOenal/multimon-ng) for decoder parity. All other logic, workflows, and documentation are original contributions from the project maintainers.
- The software is provided strictly for research, testing, and educational exploration. It is **not** a replacement for FCC-certified Emergency Alert System hardware or services and must not be relied upon for life or property protection.

## 2. No Production Deployment or Warranties
- The platform is **not** ready for production use. No representations or warranties are made about the accuracy, completeness, reliability, availability, or timeliness of the system.
- All outputs—including audio files, logs, dashboards, and reports—may contain defects or omissions. Field validation and regulatory certification have **not** been completed.
- You assume all risk for evaluating the software in lab or demonstration environments. The project is provided strictly on an “AS IS” basis without warranties of any kind.

## 3. Disclaimer of Liability & Indemnification
- The authors, maintainers, and contributors disclaim any liability for damages, injuries, penalties, or regulatory actions that may arise from use or misuse of EAS Station.
- No emergency responses, broadcast activations, or public warning decisions should be based on this project. Use at your own risk.
- You agree to indemnify, defend, and hold harmless the project authors, maintainers, and contributors from any claims arising out of your deployment, modification, or redistribution of the project.

## 4. Acceptable Use & Prohibited Activities
- Operate the software only in controlled, non-production lab or development environments.
- Do not present generated outputs as official alerts or public information.
- Do not connect EAS Station directly to transmitter plants, IPAWS live interfaces, dispatch systems, or any life-safety infrastructure.
- Do not use the project to transmit, relay, spoof, or interfere with authorized public warning systems or licensed broadcast facilities.
- Retain attribution to the project and respect the licenses of any incorporated open-source dependencies.

## 5. Data Handling, Privacy, and Logging
- The project is not designed to store protected personal information. Avoid ingesting sensitive or regulated data. If you choose to process such data, you are solely responsible for implementing appropriate safeguards and compliance controls.
- System logs, metrics, and audio captures may include time-stamped operational details. You are responsible for reviewing, redacting, or deleting this material before sharing it externally.
- No guarantee is made that encryption, access controls, or secure deletion mechanisms will meet your organizational or regulatory requirements.

## 6. Security Expectations
- You are responsible for securing any deployment, including network isolation, credential management, TLS termination, and operating system hardening.
- The maintainers do not warrant that the software is free of vulnerabilities. Promptly apply security updates, review dependency advisories, and perform your own penetration testing before exposing any component to untrusted networks.

## 7. External References & Third-Party Components
- Comparisons to third-party projects (e.g., multimon-ng) are for feature parity checks only. Those projects are governed by their respective licenses and are not endorsed by, nor affiliated with, EAS Station.
- Third-party libraries, firmware, container images, and hardware integrations are subject to their own licenses and warranties. You are responsible for reviewing and complying with those terms.

## 8. Licensing & Contributions
- The EAS Station source code is dual-licensed under the [GNU Affero General Public License v3 (AGPL-3.0)](../../LICENSE) for open-source use and a [Commercial License](../../LICENSE-COMMERCIAL) for proprietary use. Copyright remains with Timothy Kramer (KR8MER).
- By submitting code, documentation, or other content, contributors agree that their work is provided under the AGPL-3.0 license unless a separate commercial agreement is in place.
- All commits must include a Developer Certificate of Origin (DCO) sign-off line (`Signed-off-by`) affirming that the contributor has the right to submit the work under the project license. Instructions are provided in [CONTRIBUTING.md](../process/CONTRIBUTING).

## 9. Updates & Change Control
- These terms may change as the project evolves. Continued use of the repository or website after an update constitutes acceptance of the revised terms.
- Significant changes will be documented in the project changelog or release notes. Operators evaluating new builds must review the published changelog, confirm the version shown in the UI (sourced from the repository `VERSION` manifest), and verify that critical workflows (alert ingest, SAME generation, GPIO control, audio playout) still function before relying on the update for lab exercises.

## 10. Export, Compliance, and Local Regulations
- You are responsible for ensuring that your use, export, or re-export of the software complies with applicable laws, including U.S. export controls and the regulations of any destination country.
- If you integrate radio hardware, transmitters, or decoders, you must comply with all licensing, spectrum, and broadcast rules that apply in your jurisdiction.

## 11. Contact
- Questions about these terms can be directed through the GitHub issue tracker.
- Do **not** submit emergency requests, personal data, or public warning content through that channel.
