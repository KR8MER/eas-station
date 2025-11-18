#!/usr/bin/env python3
"""Replay curated SAME audio and verify alert activation logic."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from app import app  # type: ignore  # noqa: E402
from app_core.location import get_location_settings  # noqa: E402
from app_core.audio.self_test import (  # noqa: E402
    AlertSelfTestHarness,
    AlertSelfTestStatus,
)

DEFAULT_SAMPLE_FILES = [
    Path("samples/ZCZC-EAS-RWT-039137+0015-3042020-KR8MER.wav"),
    Path("samples/ZCZC-EAS-RWT-042001-042071-042133+0300-3040858-WJONTV.wav"),
]

STATUS_ICONS = {
    AlertSelfTestStatus.FORWARDED: "✅",
    AlertSelfTestStatus.FILTERED: "⚪️",
    AlertSelfTestStatus.SUPPRESSED_DUPLICATE: "🟡",
    AlertSelfTestStatus.DECODE_ERROR: "❌",
}


def _load_configured_fips(override: Iterable[str]) -> List[str]:
    if override:
        return [code for code in override if code]

    with app.app_context():
        settings = get_location_settings()
        return list(settings.get('fips_codes') or [])


def _resolve_audio_paths(user_paths: List[str], use_defaults: bool) -> List[Path]:
    paths: List[Path] = [Path(p).expanduser() for p in user_paths]
    if paths:
        return paths
    if not use_defaults:
        raise SystemExit("No audio paths provided. Specify files or omit --no-default-samples to use bundled captures.")
    return [REPO_ROOT / path for path in DEFAULT_SAMPLE_FILES]


def _format_match_list(codes: List[str]) -> str:
    return ','.join(codes) if codes else '—'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'audio',
        nargs='*',
        help='Paths to WAV/MP3 files containing SAME headers. Defaults to bundled RWT captures when omitted.',
    )
    parser.add_argument(
        '--fips',
        nargs='+',
        default=None,
        help='Override configured FIPS codes for filtering.',
    )
    parser.add_argument(
        '--require-match',
        action='store_true',
        help='Exit with status 3 if no provided sample produced a forwarded alert.',
    )
    parser.add_argument(
        '--cooldown',
        type=float,
        default=30.0,
        help='Duplicate detection window used during the test (seconds).',
    )
    parser.add_argument(
        '--source-name',
        default='self-test',
        help='Label to assign to the simulated audio source.',
    )
    parser.add_argument(
        '--no-default-samples',
        action='store_true',
        help='Do not use the bundled RWT captures when no audio paths are provided.',
    )

    args = parser.parse_args()

    audio_paths = _resolve_audio_paths(args.audio, use_defaults=not args.no_default_samples)
    configured_fips = _load_configured_fips(args.fips or [])

    harness = AlertSelfTestHarness(
        configured_fips,
        duplicate_cooldown_seconds=args.cooldown,
        source_name=args.source_name,
    )

    results = harness.run_audio_files(audio_paths)

    print("\nEAS Alert Self-Test")
    print("=" * 72)
    print(f"Configured FIPS: {', '.join(configured_fips) if configured_fips else 'None (all alerts will be filtered)'}")
    print(f"Audio samples: {len(audio_paths)}")
    print(f"Duplicate cooldown: {args.cooldown:.1f}s")
    print()
    print(f"{'Result':<8} {'Event':<8} {'Origin':<7} {'Matched FIPS':<18} {'File'}")
    print("-" * 72)

    forwarded_count = 0
    decode_errors = 0

    for item in results:
        icon = STATUS_ICONS.get(item.status, '•')
        if item.status == AlertSelfTestStatus.FORWARDED:
            forwarded_count += 1
        if item.status == AlertSelfTestStatus.DECODE_ERROR:
            decode_errors += 1
        reason_suffix = f" ({item.reason})" if item.reason else ""
        file_name = Path(item.audio_path).name
        print(
            f"{icon} {item.status.value:<18} {item.event_code:<8} {item.originator:<7} "
            f"{_format_match_list(item.matched_fips_codes):<18} {file_name}{reason_suffix}"
        )

    print("-" * 72)
    print(f"Forwarded alerts: {forwarded_count}")
    if decode_errors:
        print(f"Decode errors: {decode_errors}")
    if not forwarded_count:
        print("No alerts would currently activate based on the configured FIPS codes.")
    print("See docs/runbooks/alert_self_test.md for interpretation guidance.")

    if decode_errors:
        return 2
    if args.require_match and forwarded_count == 0:
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
