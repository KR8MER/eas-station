# ⚖️ Terms of Use

_Last updated: May 22, 2026_

> **Critical Safety Notice:** EAS Station™ is experimental software. It must not be used for life-safety, mission-critical, or FCC-mandated alerting. Commercially certified EAS equipment remains the only acceptable solution for regulatory compliance.

## 1. Project Status & Intended Use
- EAS Station™ is a community-driven development project currently in a pre-production, experimental phase with a roadmap focused on matching the functionality of commercial encoder/decoder hardware using off-the-shelf components.
- The reference build now leverages Raspberry Pi 5 compute modules (4 GB RAM baseline) paired with GPIO relay HATs, RS-232 interfaces, SDR receivers, and broadcast-grade audio cards. Raspberry Pi 4 hardware remains compatible for lab work, but it is no longer the documented baseline. None of these components are an approved substitute for certified encoder/decoder equipment until the software attains formal authorization.
- The codebase has been cross-checked against open-source utilities such as [multimon-ng](https://github.com/EliasOenal/multimon-ng) for decoder parity. All other logic, workflows, and documentation are original contributions from the project maintainers.
- The software is provided strictly for research, testing, and educational exploration. It is **not** a replacement for FCC-certified Emergency Alert System hardware or services and must not be relied upon for life or property protection.

## 2. No Production Deployment or Warranties
- The platform is **not** ready for production use. No representations or warranties are made about the accuracy, completeness, reliability, availability, or timeliness of the system.
- All outputs—including audio files, logs, dashboards, and reports—may contain defects or omissions. Field validation and regulatory certification have **not** been completed.
- You assume all risk for evaluating the software in lab or demonstration environments. The project is provided strictly on an “AS IS” basis without warranties of any kind.

## 3. Disclaimer of Liability & Indemnification
- To the maximum extent permitted by law, the authors, maintainers, and contributors disclaim liability for damages, penalties, data loss, downtime, enforcement actions, or claims arising from your use, misuse, deployment, or redistribution of EAS Station™.
- No emergency response, broadcast activation, or public warning decision should be based on this project.
- You are solely responsible for securing your deployment, controlling access, and complying with applicable law.
- You agree to defend, indemnify, and hold harmless the project authors, maintainers, and contributors from third-party claims, losses, and expenses (including reasonable attorneys' fees) arising from your deployment, operation, or misuse of the software.

## 4. Acceptable Use & Prohibited Activities
- Operate the software only in controlled, non-production lab or development environments.
- Do not present generated outputs as official alerts or public information.
- Do not connect EAS Station™ directly to transmitter plants, IPAWS live interfaces, dispatch systems, or any life-safety infrastructure.
- Do not use the project to transmit, relay, spoof, or interfere with authorized public warning systems or licensed broadcast facilities.
- Do not use the project for any malicious, unlawful, deceptive, surveillance, harassment, or disruptive purpose—including denial of service, spoofing, jamming, or unauthorized interception of communications.
- You are solely responsible for restricting access to your deployment and for any downstream impacts caused by third parties who use, repurpose, or chain this software into other tools.
- Retain attribution to the project and respect the licenses of any incorporated open-source dependencies.

## 4a. Criminal Liability & Federal Law Violations

> ⚠️ **Criminal Warning:** Misuse of this software may constitute one or more felonies under federal law and the laws of multiple states and jurisdictions. Ignorance of these laws is not a defense.

Misuse of EAS Station™—including unauthorized broadcast, spoofing, or interference with public warning systems—may constitute serious criminal offenses under United States federal law and the laws of multiple states and jurisdictions worldwide. You acknowledge and agree that:

- **Unauthorized transmission of false Emergency Alert System signals** is a federal crime under **18 U.S.C. § 1038** (False Information and Hoaxes), punishable by up to five (5) years imprisonment per offense, plus civil penalties and restitution, for each broadcast that elicits or is likely to elicit an emergency response.
- **Willful interference with authorized Emergency Alert System broadcasts** may violate **47 U.S.C. § 325** and **47 U.S.C. § 333**, and related provisions of the Communications Act of 1934 (as amended), subject to fines of up to $100,000 per violation per day under 47 U.S.C. § 503(b), criminal prosecution under **47 U.S.C. § 501**, and forfeiture of equipment. **Critically, the $100,000 fine applies independently to each station or broadcaster that relays the signal.** Because EAS operates as an automated cascade relay network, a single conforming SAME-encoded transmission propagates automatically to every downstream participant with no further human action required. Triggering a state-level Primary Entry Point (PEP) station can force hundreds of broadcasters to re-transmit the signal simultaneously, each incurring its own separate $100,000-per-day forfeiture—potentially aggregating to tens of millions of dollars in FCC fines from a single transmission.
- **Transmission of false distress signals** is a criminal offense under **47 U.S.C. § 325(a)**, subject to criminal fines and imprisonment.
- **State and local laws** in virtually all U.S. jurisdictions impose additional criminal penalties—including felony charges—for false emergency alerts, false fire alarms, or interference with emergency communications systems. Criminal charges from multiple jurisdictions may be pursued simultaneously for a single act of misuse.
- **In Ohio specifically**, misuse of this software may additionally violate:
  - **Ohio Revised Code § 2917.31** (Inducing Panic) — prohibits initiating or circulating a false report or warning of an alleged or impending fire, explosion, crime, or other catastrophe with the purpose of causing public inconvenience or alarm, or with knowledge that such report or warning will cause public inconvenience or alarm. A violation is a **fourth-degree felony** and may be elevated depending on the harm caused.
  - **Ohio Revised Code § 2913.04** (Unauthorized Use of Computer, Cable, or Telecommunication Property) — prohibits knowingly using or accessing computer, cable, or telecommunication property—including broadcast or transmission infrastructure—without the consent of the owner or authorized user. A violation is a **fifth-degree felony** and may be elevated to a third-degree felony if the unauthorized access disrupts public services or emergency communications.
  - **Ohio Revised Code § 2909.04** (Disrupting Public Services) — prohibits knowingly disrupting, interrupting, or impairing the ability of authorized persons to receive emergency services, including radio or other communications systems used by emergency responders or public warning systems. A violation is a **fourth-degree felony**.
  - **Ohio Revised Code § 2917.32** (Making False Alarms) — prohibits initiating or announcing a false alarm of fire, explosion, flood, avalanche, or other disaster requiring emergency response, or causing another to initiate or announce such a false alarm. A violation is a **first-degree misdemeanor** and escalates to a **fourth-degree felony** if it results in serious physical harm to any person, or if the offender has a prior conviction for the same offense.
  - **Ohio Revised Code § 2921.31** (Obstructing Official Business) — prohibits knowingly hampering or impeding a public official or employee in the performance or discharge of any authorized duty. Misuse that interferes with authorized emergency broadcasts, disrupts emergency response coordination, or prevents lawful EAS relay is a violation. A violation is a **second-degree misdemeanor** and escalates to a **fifth-degree felony** when the conduct creates a risk of physical harm to any person.
- In jurisdictions outside the United States, equivalent or more severe criminal statutes may apply, and international law enforcement cooperation may result in prosecution across borders.
- To the maximum extent permitted by law, the developer, maintainers, and contributors disclaim criminal, civil, and regulatory liability for acts or omissions committed by persons using this software. You remain responsible for your own conduct and legal compliance.
- The project authors are not accomplices, aiders, or abettors of any misuse and explicitly disclaim any knowledge of, participation in, or responsibility for any illegal activity conducted using this software. The existence of this software does not constitute authorization, endorsement, or facilitation of any unlawful act.

## 4b. Documented Real-World Enforcement Cases

> EAS Station™ generates **valid**, standards-compliant SAME-encoded audio that has been confirmed by testing across multiple receivers to activate ENDEC hardware and software relay equipment—exactly as a live alert would. The cases below are real documented enforcement actions that arose from exactly this type of signal. They are directly applicable to any output produced by this software.

> ⚠️ **This software has not received FCC certification or regulatory approval as an EAS encoder/decoder.** EAS Station™ is a software-based reference implementation designed to replicate the functionality of certified hardware devices such as the Digital Alert Systems DASDEC. It is **not an approved substitute** for certified EAS encoder/decoder equipment under **47 C.F.R. Part 11** and **must not be installed anywhere within a commercial broadcast air-chain**, used by any FCC-licensed EAS Participant, or used to originate or relay alerts over any facility subject to FCC Part 11 obligations.
>
> The intended use case for this software is **licensed amateur radio operators** operating under **47 C.F.R. Part 97**, who are not FCC EAS Participants and are not subject to the Part 11 certification requirements that mandate the use of approved encoder/decoder equipment. Amateur radio operators may lawfully use EAS-compatible audio for training, experimentation, and emergency communications exercises within the scope of Part 97 and within the terms of this agreement.
>
> Understanding why this boundary is critical requires understanding how EAS relay propagation works. The Emergency Alert System was engineered for maximum geographic reach and relay reliability — not for security. Every EAS Participant station is configured by default to automatically re-broadcast any conforming SAME-encoded signal it receives. There is no cryptographic authentication, no sender verification, and no human approval gate in the relay chain. A correctly-formatted SAME header at the correct bit rate is the only credential the system evaluates. A single conforming transmission injected anywhere in the network propagates automatically and without human intervention to every downstream participant. A state-level Primary Entry Point (PEP) activation can force hundreds of broadcasters to re-transmit a false alert across an entire state in seconds — all without any human ever reviewing or approving the signal. EAS Station™ produces output that is indistinguishable from a live, authorized alert by the relay equipment that governs this cascade. This is not theoretical — the Montana incident (Case 3 below) is direct, documented proof.

### Case 1 — iHeartMedia / *The Bobby Bones Show*, $1,000,000 Consent Decree (2015)

iHeartMedia aired counterfeit EAS Attention Signals (the two-tone 853/960 Hz sequence) during *The Bobby Bones Show* on multiple iHeartMedia stations as part of a comedy segment. The signals were sufficiently well-formed to be intercepted as real alerts. The FCC's Enforcement Bureau initiated proceedings and iHeartMedia entered into a **Consent Decree (FCC DA 15-199)** requiring payment of a **$1,000,000 civil penalty**, adoption of a mandatory EAS compliance program, and multi-year reporting to the FCC. The decree explicitly states that broadcasting EAS tones outside authorized emergency or test use violates 47 C.F.R. § 11.45 regardless of intent.

Source: FCC DA 15-199 — <https://docs.fcc.gov/public/attachments/DA-15-199A1.pdf>

### Case 2 — *Olympus Has Fallen* Movie Trailer, $1,900,000 Multi-Network Settlement (2014)

A theatrical trailer for the film *Olympus Has Fallen* contained EAS Attention Signals and was aired across multiple national broadcast and cable networks. The signals activated receiving equipment and constituted an unauthorized transmission under 47 C.F.R. § 11.45. The FCC issued Notices of Apparent Liability to the networks involved; the proceedings concluded in a combined **settlement of $1,900,000 (FCC DA 14-1097)** across the multiple licensees. This case established that unauthorized EAS signal transmission liability attaches to *every entity* in the distribution chain—not only the original content producer.

Source: FCC DA 14-1097 — <https://docs.fcc.gov/public/attachments/DA-14-1097A1.pdf>

### Case 3 — Montana "Zombie Apocalypse" EAS Cascade Hack (January 11, 2013)

Attackers gained unauthorized access to EAS encoder/decoder hardware at KRTV-TV (Great Falls, MT) and KXLH (Helena, MT) and injected a fabricated SAME-encoded alert stating: *"Civil authorities in your area have reported that the bodies of the dead are rising from their graves and attacking the living."* Because the injected SAME headers were correctly formatted and encoded at the proper bit rate, receiving equipment throughout the Montana EAS relay network **automatically re-broadcast the message** without further human action—demonstrating the inherent cascade behavior of the EAS relay system when presented with a conforming signal. The FCC issued Public Advisory **DA 13-108** warning all EAS Participants about equipment security vulnerabilities and opened enforcement proceedings against the affected stations. The incident is cited in FCC guidance as direct evidence that properly formatted EAS signals trigger automated relay with no human gate.

Source: FCC Public Advisory DA 13-108 — <https://docs.fcc.gov/public/attachments/DA-13-108A1.pdf>

### Case 4 — Multi-Party EAS/WEA Tone Settlements, $600,000+ in Combined Penalties (2019)

On August 15, 2019, the FCC Enforcement Bureau simultaneously adopted consent decrees against four media companies for transmitting EAS or Wireless Emergency Alert (WEA) tones outside any actual emergency or authorized test, in violation of 47 C.F.R. § 11.45. The combined civil penalties exceeded **$600,000**:

- **ABC, Inc. — $395,000** for broadcasting the WEA Attention Signal during a comedy segment on *Jimmy Kimmel Live!* (October 3, 2018).
- **AMC Networks — $104,000** for transmitting EAS tones twice during *The Walking Dead* scripted drama "Omega" episode (February 2019).
- **Discovery Communications — $68,000** for EAS tones aired on *Animal Planet* programming.
- **Meruelo Radio Holdings — $67,000** for EAS/WEA tones aired on a radio broadcast.

This action is directly applicable to the use of EAS Station™ output: it confirms that EAS/WEA tones embedded in **comedy** (*Jimmy Kimmel*) and **scripted television drama** (*The Walking Dead*) draw federal enforcement regardless of the fictional or entertainment framing of the content.

Source: FCC, "FCC Settles Investigations Into Misuse of Emergency Alert Tones" (Public Notice DOC-359101A1) — <https://docs.fcc.gov/public/attachments/DOC-359101A1.pdf>

### Case 5 — Paramount Global, $244,952 Consent Decree (2024)

On December 18, 2024, the FCC entered a consent decree with Paramount Global resolving investigations into the transmission of EAS codes or the Attention Signal—or recordings or simulations thereof—across three CBS properties: the scripted series *Young Sheldon* (May 18, 2023), in a dramatized scene depicting characters reacting to an **impending tornado**; the syndicated program *Entertainment Tonight* (October 25, 2023); and the *CBS News Radio "Top of the Hour"* broadcast (June 6, 2024). Paramount Global agreed to a compliance plan and a **$244,952 civil penalty**.

The *Young Sheldon* portion is squarely on point for this software: a **fictional, dramatized emergency** in scripted entertainment—exactly the kind of "imagined" alert scenario prohibited in Section 4c—was itself sufficient to trigger FCC enforcement.

Source: FCC Consent Decree DA 24-1285 — <https://docs.fcc.gov/public/attachments/DA-24-1285A1.pdf>

### Case 6 — Ongoing FCC EAS Enforcement Pattern (2013–present)

Since 2013 the FCC Enforcement Bureau has entered into consent decrees and issued forfeiture orders against dozens of licensees for EAS tone misuse in advertisements, movie trailers, comedic content, podcasts, and streaming programming. Individual per-violation forfeitures have ranged from **$8,000 to $325,000**, and consent decree civil penalties have reached seven figures. Enforcement actions routinely include mandatory compliance programs, annual reporting obligations, and the possibility of license revocation under 47 U.S.C. § 312. All FCC enforcement records are publicly searchable at <https://www.fcc.gov/enforcement/orders>.

Applicable rules: 47 C.F.R. § 11.45 (prohibition on EAS code/Attention Signal use outside emergencies and tests); 47 U.S.C. § 503(b) (forfeiture authority up to $100,000/violation/day); 47 U.S.C. § 501 (criminal penalties up to $10,000 fine and 1 year imprisonment per violation).

## 4c. Real Operational Semantics Only — No Fictional or Entertainment Use
EAS Station™ is intended to faithfully model the **actual operational semantics** of certified EAS encoder/decoder equipment — the same SAME header structure, attention-tone characteristics, EOM behavior, relay-cascade logic, and timing tolerances that live broadcast hardware implements. That fidelity is what makes the project useful for research, training, amateur-radio experimentation, and standards work, and it is also what makes the project unsuitable as a content-creation toolkit. You agree that:

- **Do not author fictional, fabricated, satirical, dramatized, or "what-if" EAS workflows or alert content.** That includes invented event codes, invented FIPS/SAME area combinations, joke alert text, parody RWT/RMT cycles, mock CAP feeds with non-real events, or any "imagined" alert scenario presented as if it were a real EAS message — whether for fun, demonstration, social media, or storytelling.
- **Do not use the software, its audio output, its dashboards, its logs, or any derivative artifact in entertainment or media production.** This explicitly includes films, television, advertising, trailers, music videos, podcasts, streaming programming, video games, machinima, YouTube/TikTok/Reels/Shorts content, livestream stunts, prank or "creepypasta" content, ARGs (alternate-reality games), haunted-attraction sound design, theatrical performance, or any other dramatic or promotional work.
- **Intent and labeling do not cure the violation.** Content clearly labeled as fiction has already triggered real EAS equipment in the real world (see the *Olympus Has Fallen* trailer enforcement action in Section 4b, Case 2). 47 C.F.R. § 11.45 prohibits broadcast of EAS codes and the Attention Signal outside actual emergencies and authorized tests **regardless of intent**, and the cascade-relay design of the EAS network does not distinguish between a "fictional" SAME header and a real one.
- **The project models real EAS semantics; it does not manufacture EAS-styled content.** Training exercises, RWT/RMT messages, and amateur-radio drills authorized under FCC Part 97 must use lawfully assignable event codes, lawfully assignable origin/area information, and must remain confined to the controlled environments described in Sections 1, 2, and 4. They are operational exercises, not creative output.
- **You are responsible for downstream use of any audio, header, or capture produced with this software.** If you publish such an artifact in any setting where it could be received, demodulated, or relayed by a third party — including upload to a public host that a streaming or broadcast workflow could later pull from — you assume full responsibility for the resulting enforcement exposure.

## 5. Enforcement & Termination
- The maintainers reserve the right to revoke access to hosted resources, documentation, or support channels for any user who violates these terms or engages in malicious or unsafe activity.
- No right to continued access, updates, or support is granted. Your permission to use the software terminates immediately if you breach these terms.

## 6. Data Handling, Privacy, and Logging
- The project is not designed to store protected personal information. Avoid ingesting sensitive or regulated data. If you choose to process such data, you are solely responsible for implementing appropriate safeguards and compliance controls.
- System logs, metrics, and audio captures may include time-stamped operational details. You are responsible for reviewing, redacting, or deleting this material before sharing it externally.
- No guarantee is made that encryption, access controls, or secure deletion mechanisms will meet your organizational or regulatory requirements.

## 6a. SMS Messaging Terms
If you enable the SMS notification feature, the following terms apply to you as the system operator:

- You may only add phone numbers belonging to individuals who have provided **explicit, prior written consent** to receive EAS alert SMS messages from your deployment of this software.
- You are solely responsible for obtaining, documenting, and honoring consent, and for complying with all applicable laws including the Telephone Consumer Protection Act (TCPA), CTIA guidelines, and applicable carrier requirements.
- Messages sent by EAS Station™ via Twilio are for **emergency alert notification purposes only**. Do not use the SMS feature for marketing, promotional, or non-emergency communications.
- You must honor opt-out requests (STOP) promptly and remove the corresponding number from the admin panel. Twilio handles STOP/HELP/CANCEL keyword processing automatically at the carrier level.
- **Message and data rates may apply** to recipients per their mobile carrier plan. Inform recipients of this before obtaining consent.
- Message frequency varies with EAS alert volume and may be high during active weather or emergency events. Disclose expected frequency to recipients prior to consent.
- The project maintainers disclaim all liability for your use of the SMS feature, including any regulatory violations, carrier fees, or claims arising from messages sent through your deployment.

See the [SMS Messaging Policy](SMS_MESSAGING.md) (served live at `/sms-compliance` on your EAS Station™ instance) for the consumer-facing disclosures required by Twilio and carriers.

## 7. Security Expectations
- You are responsible for securing any deployment, including network isolation, credential management, TLS termination, and operating system hardening.
- The maintainers do not warrant that the software is free of vulnerabilities. Promptly apply security updates, review dependency advisories, and perform your own penetration testing before exposing any component to untrusted networks.

## 8. External References & Third-Party Components
- Comparisons to third-party projects (e.g., multimon-ng) are for feature parity checks only. Those projects are governed by their respective licenses and are not endorsed by, nor affiliated with, EAS Station™.
- Third-party libraries, firmware, container images, and hardware integrations are subject to their own licenses and warranties. You are responsible for reviewing and complying with those terms.

## 9. Licensing & Contributions
- The EAS Station™ source code is dual-licensed under the [GNU Affero General Public License v3 (AGPL-3.0)](../../LICENSE) and a [Commercial License](../../LICENSE-COMMERCIAL). AGPL availability is not limited to non-commercial users; commercial users may also use AGPL if they comply with its terms. Copyright remains with EAS Station, LLC (KR8MER).
- By submitting code, documentation, or other content, contributors agree that their work is provided under the AGPL-3.0 license unless a separate commercial agreement is in place.
- All commits must include a Developer Certificate of Origin (DCO) sign-off line (`Signed-off-by`) affirming that the contributor has the right to submit the work under the project license. Instructions are provided in [CONTRIBUTING.md](../process/CONTRIBUTING.md).

## 10. Updates & Change Control
- These terms may change as the project evolves. Continued use of the repository or website after an update constitutes acceptance of the revised terms.
- Significant changes will be documented in the project changelog or release notes. Operators evaluating new builds must review the published changelog, confirm the version shown in the UI (sourced from the repository `VERSION` manifest), and verify that critical workflows (alert ingest, SAME generation, GPIO control, audio playout) still function before relying on the update for lab exercises.

## 11. Export, Compliance, and Local Regulations
- You are responsible for ensuring that your use, export, or re-export of the software complies with applicable laws, including U.S. export controls and the regulations of any destination country.
- If you integrate radio hardware, transmitters, or decoders, you must comply with all licensing, spectrum, and broadcast rules that apply in your jurisdiction.

## 12. Contact
- Questions about these terms can be directed through the GitHub issue tracker.
- Do **not** submit emergency requests, personal data, or public warning content through that channel.

## 13. General Contract Terms
- **Governing Law and Venue:** Unless superseded by a separate written agreement, these terms are governed by the laws of the State of Ohio, United States, without regard to conflict-of-law principles. Any dispute arising from these terms must be brought in state or federal courts located in Ohio.
- **Severability:** If any provision is held unenforceable, remaining provisions remain in full force.
- **Waiver:** Failure to enforce any provision is not a waiver of future enforcement.
- **Entire Agreement for Site Terms:** These Terms of Use, together with referenced policy pages, form the entire agreement for use of this website and related project resources.
- **Updates to Terms:** We may update these terms from time to time by posting a revised version with a new "Last updated" date.
- **Capacity:** By using this site, you represent that you have legal capacity to enter into this agreement in your jurisdiction.
- **Legal Notices Contact:** For legal notices, contact sales@easstation.com.

## 14. Relationship to Software Licenses
- These Terms of Use govern access to and use of the website, documentation, and related resources.
- These Terms of Use do **not** replace, modify, or override the software copyright licenses.
- Use, modification, and distribution of source code are governed by the [AGPL-3.0 License](../../LICENSE) or the [Commercial License](../../LICENSE-COMMERCIAL), as applicable.

## 15. AMPR Network (44.0.0.0/8) — Non-Commercial Use

This service may be accessible via the **AMPRNet** IPv4 address block (`44.0.0.0/8`), which is allocated globally to the licensed amateur radio community by the [Amateur Radio Digital Communications (ARDC)](https://www.ampr.org/) foundation and managed under amateur radio service rules (FCC 47 CFR Part 97 in the United States).

In accordance with FCC Part 97, ARDC allocation policy, and the terms governing the AMPRNet address space:

- **This service is strictly NON-COMMERCIAL.** No commercial activity, for-profit transactions, or commercial advertising of any kind is conducted through this AMPRNet-accessible endpoint.
- This deployment is operated by a licensed amateur radio operator (KR8MER) for non-commercial research, experimentation, and emergency communications training.
- Any use of this service via the 44.0.0.0/8 address space must remain consistent with FCC Part 97 non-commercial requirements.
- Commercial exploitation of the 44.0.0.0/8 block is prohibited under ARDC allocation policy and applicable FCC regulations.

For information on the AMPRNet allocation and acceptable use policy, see [ampr.org](https://www.ampr.org/).
For the FCC Part 97 rules governing amateur radio service, see [47 CFR Part 97](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-97).
