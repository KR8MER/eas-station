"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

"""Conformance test pinning the SAME event-code registry to NWS Instruction
10-1712, *NOAA Weather Radio All Hazards (NWR) Specific Area Message Encoding
(SAME)*, dated April 20, 2022, Appendix A.4.

The directive groups codes into:
  A.4.1   Weather-related events (optional for FCC-regulated broadcast stations)
  A.4.2.1 National non-weather codes (required for FCC-regulated stations)
  A.4.2.2 State and local non-weather codes (optional)
  A.4.2.3 Administrative events (optional)
  A.4.3   NWR transmitter control codes (NOT EAS, NOT for SAME receivers)

EAS Station encodes/decodes SAME, so every EAS-relevant code in A.4.1, A.4.2,
and A.4.3-excluded set must resolve to a human-readable name. The A.4.3
transmitter-control codes (TXF/TXO/TXB/TXP) are deliberately excluded because
the directive states they "are not intended to be implemented on SAME-capable
receivers."
"""

import unittest

from app_utils.event_codes import (
    EVENT_CODE_REGISTRY,
    resolve_event_code_from_name,
)


# Appendix A.4.1 — Weather-related events.
NWS_10_1712_WEATHER_CODES = {
    "BZW", "CFA", "CFW", "DSW", "EWW", "FFA", "FFW", "FFS", "FLA", "FLW",
    "FLS", "HWA", "HWW", "HUA", "HUW", "HLS", "SVA", "SVR", "SVS", "SMW",
    "SPS", "SQW", "SSW", "SSA", "TOA", "TOR", "TRA", "TRW", "TSA", "TSW",
    "WSA", "WSW",
}

# Appendix A.4.2.1 — National non-weather codes (required for broadcast).
NWS_10_1712_NATIONAL_CODES = {"EAN", "NIC", "NPT", "RMT", "RWT"}

# Appendix A.4.2.2 — State and local non-weather codes.
NWS_10_1712_STATE_LOCAL_CODES = {
    "ADR", "AVA", "AVW", "BLU", "CAE", "CDW", "CEM", "EQW", "EVI", "FRW",
    "HMW", "LEW", "LAE", "TOE", "NUW", "RHW", "SPW", "VOW",
}

# Appendix A.4.2.3 — Administrative events.
NWS_10_1712_ADMIN_CODES = {"NMN", "DMO"}

# Appendix A.4.3 — NWR transmitter control codes. These are explicitly NOT EAS
# and NOT meant to be implemented on SAME receivers, so EAS Station must NOT
# treat them as airable event codes.
NWS_10_1712_TRANSMITTER_CONTROL_CODES = {"TXF", "TXO", "TXB", "TXP"}

NWS_10_1712_EAS_CODES = (
    NWS_10_1712_WEATHER_CODES
    | NWS_10_1712_NATIONAL_CODES
    | NWS_10_1712_STATE_LOCAL_CODES
    | NWS_10_1712_ADMIN_CODES
)


class TestNws101712EventCodeCoverage(unittest.TestCase):
    def test_all_eas_relevant_codes_present(self):
        """Every EAS-relevant code in 10-1712 Appendix A.4 is in the registry."""
        missing = sorted(NWS_10_1712_EAS_CODES - set(EVENT_CODE_REGISTRY))
        self.assertEqual(
            missing, [],
            "Event codes required by NWSI 10-1712 (2022) are missing from "
            f"EVENT_CODE_REGISTRY: {missing}",
        )

    def test_codes_added_in_april_2022_revision(self):
        """The four codes the April 20, 2022 revision introduced are present.

        BLU, SQW, SSA, SSW, and EWW were the products addressed in the
        revision's summary of changes; SQW already existed, so this guards the
        four that were previously absent.
        """
        for code in ("EWW", "SSW", "SSA", "BLU"):
            self.assertIn(
                code, EVENT_CODE_REGISTRY,
                f"{code} (added/addressed in NWSI 10-1712 April 2022) is missing",
            )

    def test_added_code_names_match_directive(self):
        expected = {
            "EWW": "Extreme Wind Warning",
            "SSW": "Storm Surge Warning",
            "SSA": "Storm Surge Watch",
            "BLU": "Blue Alert",
        }
        for code, name in expected.items():
            self.assertEqual(EVENT_CODE_REGISTRY[code]["name"], name)

    def test_added_codes_resolve_by_name(self):
        """A CAP alert headline maps back to the new codes via name lookup."""
        self.assertEqual(resolve_event_code_from_name("Extreme Wind Warning"), "EWW")
        self.assertEqual(resolve_event_code_from_name("Storm Surge Warning"), "SSW")
        self.assertEqual(resolve_event_code_from_name("Storm Surge Watch"), "SSA")
        self.assertEqual(resolve_event_code_from_name("Blue Alert"), "BLU")

    def test_transmitter_control_codes_excluded(self):
        """NWR control codes (A.4.3) must not be registered as EAS event codes."""
        present = sorted(
            NWS_10_1712_TRANSMITTER_CONTROL_CODES & set(EVENT_CODE_REGISTRY)
        )
        self.assertEqual(
            present, [],
            "NWR transmitter-control codes from 10-1712 A.4.3 must not be "
            f"treated as airable SAME event codes: {present}",
        )


if __name__ == "__main__":
    unittest.main()
