"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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

"""Tests for the Pi auto-deploy and watchdog (docs/maintenance/PI_AUTODEPLOY.md).

The deploy script runs as root from a sudoers rule, so its safety
properties are pinned here as text checks: if one is edited away, CI fails
before the change can be reinstalled on the Pi. The watchdog's decision
logic is pure and tested directly.
"""

import importlib.util
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "scripts" / "deploy" / "eas-deploy.sh"
SUDOERS = ROOT / "config" / "sudoers-gh-runner"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-pi.yml"

_spec = importlib.util.spec_from_file_location(
    "eas_watchdog", ROOT / "scripts" / "deploy" / "eas_watchdog.py"
)
wd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wd)


# ------------------------------------------------------------ deploy script

def test_deploy_script_is_valid_bash():
    subprocess.run(["bash", "-n", str(DEPLOY)], check=True)


def test_deploy_only_accepts_origin_main_tip():
    text = DEPLOY.read_text()
    assert re.search(r'\[\[ "\$SHA" =~ \^\[0-9a-f\]\{40\}\$ \]\]', text)
    assert 'git rev-parse origin/main' in text
    assert '[ "$SHA" = "$TIP" ] || fail' in text


def test_deploy_refuses_hand_edits_in_opt():
    assert "git status --porcelain --untracked-files=no" in DEPLOY.read_text()


def test_deploy_waits_for_alert_then_migrates_before_restart():
    text = DEPLOY.read_text()
    migrate = text.index("alembic upgrade head")
    wait = text.index("\nwait_for_air\n")
    restart = text.index('systemctl restart "$TARGET"')
    assert migrate < restart and wait < restart
    assert "eas:broadcast_active" in text


def test_deploy_rolls_back_on_failed_health_check():
    text = DEPLOY.read_text()
    assert 'git reset -q --hard $PREV' in text
    assert text.index("if healthy; then") < text.index('git reset -q --hard $PREV')


def test_sudoers_allows_exactly_one_command():
    rules = [ln for ln in SUDOERS.read_text().splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    assert rules == ["gh-runner ALL=(root) NOPASSWD: /usr/local/sbin/eas-deploy"]


# ---------------------------------------------------------------- workflow

def test_workflow_never_runs_on_pull_requests():
    triggers = yaml.safe_load(WORKFLOW.read_text())[True]
    assert set(triggers) == {"push", "schedule", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["main"]


def test_deploy_job_runs_no_repo_code():
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["deploy"]
    assert job["runs-on"] == ["self-hosted", "eas-pi"]
    assert all("uses" not in step for step in job["steps"])
    assert [s["run"] for s in job["steps"]] == ['sudo -n /usr/local/sbin/eas-deploy "$SHA"']


# ------------------------------------------------------------------ watchdog

def _mp3_frames(kbps_index, version_bits=0b11, count=5):
    # 0xFFFB-style MPEG-1 Layer III header with the given bitrate index.
    b1 = 0xE0 | (version_bits << 3) | (0b01 << 1) | 1
    frame = bytes([0xFF, b1, (kbps_index << 4) | (0 << 2), 0x00]) + b"\x00" * 100
    return frame * count


def test_mp3_bitrate_is_read_from_frame_headers():
    assert wd.mp3_bitrate_kbps(b"junk" + _mp3_frames(9)) == 128    # MPEG-1 L3 index 9
    assert wd.mp3_bitrate_kbps(_mp3_frames(8, version_bits=0b10)) == 64  # MPEG-2 L3
    assert wd.mp3_bitrate_kbps(b"\x00" * 500) is None


def test_stream_ratio():
    assert abs(wd.stream_ratio(160_000, 10.0, 128) - 1.0) < 1e-9
    assert abs(wd.stream_ratio(96_000, 10.0, 128) - 0.6) < 1e-9


def _samples(hours, start_mb, mb_per_hour, every_h=1.0):
    n = int(hours / every_h) + 1
    return [(i * every_h * 3600, int((start_mb + mb_per_hour * i * every_h) * 2**20))
            for i in range(n)]


def test_steady_growth_is_reported_as_a_leak():
    # The demod leak: ~25 MB/h.
    assert "growing" in wd.leak_verdict(_samples(8, 330, 25))


def test_flat_or_short_or_spiky_memory_is_not_a_leak():
    assert wd.leak_verdict(_samples(24, 400, 0)) is None
    assert wd.leak_verdict(_samples(3, 330, 25)) is None        # too little history
    spike = _samples(8, 400, 0)
    spike[3] = (spike[3][0], spike[3][1] + 500 * 2**20)         # one transient spike
    assert wd.leak_verdict(spike) is None


def test_history_resets_when_the_service_restarts():
    state = {}
    wd.update_history(state, "u", "inv-1", 0, 100)
    assert len(wd.update_history(state, "u", "inv-1", 3600, 200)) == 2
    assert wd.update_history(state, "u", "inv-2", 7200, 50) == [(7200, 50)]


def test_old_samples_are_dropped():
    state = {"u": {"invocation": "i", "samples": [(0, 1)]}}
    assert wd.update_history(state, "u", "i", wd.HISTORY_S + 10, 2) == [(wd.HISTORY_S + 10, 2)]
