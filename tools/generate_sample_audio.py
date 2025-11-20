#!/usr/bin/env python3
"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

from __future__ import annotations

"""Generate a demo SAME audio file (optionally with Azure voiceover)."""

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app_utils.eas import EASAudioGenerator, build_same_header, load_eas_config


def _build_sample_alert(now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        identifier="SAMPLE-ALERT-0001",
        event="Required Weekly Test",
        headline="This is a demonstration of the NOAA alerting node.",
        description=(
            "The Emergency Alert System is conducting a test of its broadcast capabilities. "
            "No action is required."
        ),
        instruction="Please stand by for further information if this were an actual emergency.",
        sent=now,
        expires=now + timedelta(minutes=30),
        status="Actual",
        message_type="Alert",
    )


def _build_sample_payload(now: datetime) -> dict:
    return {
        "identifier": "SAMPLE-ALERT-0001",
        "sent": now,
        "expires": now + timedelta(minutes=30),
        "status": "Actual",
        "message_type": "Alert",
        "raw_json": {
            "properties": {
                "geocode": {
                    "SAME": ["012345", "678901"],
                }
            }
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-path",
        type=Path,
        default=None,
        help="Project base path (defaults to current working directory)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override the audio output directory",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    logger = logging.getLogger("sample-audio")

    config = load_eas_config(str(args.base_path) if args.base_path else None)
    if args.output_dir:
        config["output_dir"] = str(args.output_dir)
    config.setdefault("enabled", True)

    now = datetime.now(timezone.utc)
    alert = _build_sample_alert(now)
    payload = _build_sample_payload(now)

    header, location_codes, _ = build_same_header(alert, payload, config)
    generator = EASAudioGenerator(config, logger)
    audio_filename, text_filename, _, _, _, _ = generator.build_files(
        alert,
        payload,
        header,
        location_codes,
    )

    output_dir = Path(generator.output_dir)
    audio_path = output_dir / audio_filename
    text_path = output_dir / text_filename

    print(f"Generated audio: {audio_path}")
    print(f"Summary: {text_path}")


if __name__ == "__main__":
    main()
