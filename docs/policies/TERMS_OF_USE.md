# ⚖️ Terms of Use

_Last updated: January 30, 2025_

> **Critical Safety Notice:** EAS Station is experimental software. It must not be used for life-safety, mission-critical, or FCC-mandated alerting. Commercially certified EAS equipment remains the only acceptable solution for regulatory compliance.

## 1. Project Status & Intended Use
- EAS Station is a community-driven development project currently in a pre-production, experimental phase with a roadmap focused on matching the functionality of commercial encoder/decoder hardware using off-the-shelf components.
- The reference build now leverages Raspberry Pi 5 compute modules (4 GB RAM baseline) paired with GPIO relay HATs, RS-232 interfaces, SDR receivers, and broadcast-grade audio cards. Raspberry Pi 4 hardware remains compatible for lab work, but it is no longer the documented baseline. None of these components are an approved substitute for certified encoder/decoder equipment until the software attains formal authorization.
- The codebase has been cross-checked against open-source utilities such as [multimon-ng](https://github.com/EliasOenal/multimon-ng) for decoder parity. All other logic, workflows, and documentation are original contributions from the project maintainers.
- The software is provided strictly for research, testing, and educational exploration. It is **not** a replacement for FCC-certified Emergency Alert System hardware or services and must not be relied upon for life or property protection.

## 2. No Production Deployment
- The platform is **not** ready for production use. No representations or warranties are made about the accuracy, completeness, or reliability of the system.
- All outputs—including audio files, logs, dashboards, and reports—may contain defects or omissions.
- You assume all risk for evaluating the software in lab or demonstration environments.

## 3. Disclaimer of Liability
- The authors, maintainers, and contributors disclaim any liability for damages, injuries, penalties, or regulatory actions that may arise from use or misuse of EAS Station.
- No emergency responses, broadcast activations, or public warning decisions should be based on this project. Use at your own risk.

## 4. Acceptable Use
- Operate the software only in controlled, non-production lab or development environments.
- Do not present generated outputs as official alerts or public information.
- Do not connect EAS Station directly to transmitter plants, IPAWS live interfaces, dispatch systems, or any life-safety infrastructure.
- Retain attribution to the project and respect the licenses of any incorporated open-source dependencies.

## 5. External References
- Comparisons to third-party projects (e.g., multimon-ng) are for feature parity checks only.
- Those projects are governed by their respective licenses and are not endorsed by, nor affiliated with, EAS Station.

## 6. Licensing & Contributions
- The EAS Station source code is released under the [MIT License](../../LICENSE). Copyright remains with Timothy Kramer (KR8MER).
- By submitting code, documentation, or other content, contributors agree that their work is provided under the MIT License.
- All commits must include a Developer Certificate of Origin (DCO) sign-off line (`Signed-off-by`) affirming that the contributor has the right to submit the work under the project license. Instructions are provided in [CONTRIBUTING.md](../process/CONTRIBUTING.md).

## 7. Updates
- These terms may change as the project evolves.
- Continued use of the repository or website after an update constitutes acceptance of the revised terms.
- Significant changes will be documented in the project changelog or release notes.
- Operators evaluating new builds must review the published changelog, confirm the version shown in the UI (sourced from the repository `VERSION` manifest), and verify that critical workflows (alert ingest, SAME generation, GPIO control, audio playout) still function before relying on the update for lab exercises.

## 8. Contact
- Questions about these terms can be directed through the GitHub issue tracker.
- Do **not** submit emergency requests, personal data, or public warning content through that channel.
