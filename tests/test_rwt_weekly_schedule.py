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

"""The Required Weekly Test fires once per week, on one of the allowed days.

The configured days are the days the broadcast is *allowed* to land on, not a
list of days to broadcast on.  Selecting Sunday and Tuesday must produce one
test that week — on a Sunday or a Tuesday — never one on each.  Varying which
day and time it lands on is also what 47 CFR 11.61(a)(2) asks for.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app_core.rwt_scheduler import (
    compute_next_fire,
    week_key,
    weekly_fire_slot,
)

TZ = timezone(timedelta(hours=-5))

# 2026-08-03 is a Monday, so this week runs 2026-08-03 (Mon) .. 2026-08-09 (Sun).
MONDAY = datetime(2026, 8, 3, 0, 0, tzinfo=TZ)

SUNDAY = 6
TUESDAY = 1


def _config(days=(SUNDAY, TUESDAY), **overrides):
    """A minimal duck-typed stand-in for RWTScheduleConfig."""
    base = dict(
        id=1,
        enabled=True,
        days_of_week=list(days),
        start_hour=8,
        start_minute=0,
        end_hour=16,
        end_minute=0,
        skip_until=None,
        last_run_at=None,
        last_run_status=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _day_of(moment):
    return moment.weekday()


# ---------------------------------------------------------------------------
# Slot selection
# ---------------------------------------------------------------------------


def test_slot_lands_on_exactly_one_allowed_day():
    """The chosen slot is on one of the ticked days, inside the window."""
    slot = weekly_fire_slot(_config(), MONDAY)

    assert slot is not None
    assert _day_of(slot) in (SUNDAY, TUESDAY)
    minutes = slot.hour * 60 + slot.minute
    assert 8 * 60 <= minutes <= 16 * 60


def test_slot_is_stable_across_the_whole_week():
    """Every moment in the week resolves to the same slot.

    The scheduler polls once a minute in each of several Gunicorn workers; they
    must all agree, and the UI's "next scheduled fire" must not jump around.
    """
    config = _config()
    slots = {
        weekly_fire_slot(config, MONDAY + timedelta(days=offset, hours=hour))
        for offset in range(7)
        for hour in (0, 9, 13, 23)
    }
    assert len(slots) == 1


def test_slot_moves_between_weeks():
    """The day/time varies week to week rather than settling on a pattern."""
    config = _config(days=(0, 1, 2, 3, 4, 5, 6))
    slots = [
        weekly_fire_slot(config, MONDAY + timedelta(weeks=w)) for w in range(12)
    ]
    assert len({s.weekday() for s in slots}) > 1, "day never varies"
    assert len({(s.hour, s.minute) for s in slots}) > 1, "time never varies"


def test_slot_respects_skip_until():
    """Days covered by skip_until are not eligible."""
    # Skip through the Tuesday of this week; only Sunday remains.
    config = _config(skip_until=(MONDAY + timedelta(days=TUESDAY)).date())
    slot = weekly_fire_slot(config, MONDAY)

    assert slot is not None
    assert _day_of(slot) == SUNDAY


def test_no_slot_when_every_allowed_day_is_skipped():
    config = _config(skip_until=(MONDAY + timedelta(days=6)).date())
    assert weekly_fire_slot(config, MONDAY) is None


def test_no_slot_when_disabled_or_no_days():
    assert weekly_fire_slot(_config(enabled=False), MONDAY) is None
    assert weekly_fire_slot(_config(days=()), MONDAY) is None


# ---------------------------------------------------------------------------
# Fire-once-per-week semantics
# ---------------------------------------------------------------------------


def _fires_on(config, now_local):
    """Replicate the scheduler's fire decision for a given moment.

    Mirrors RWTScheduler._check_and_send_rwt so the week-level rules can be
    exercised without a database, a Flask app, or the audio pipeline.
    """
    from app_core.rwt_scheduler import (
        _eligible_days,
        _ran_in_week,
        _window_bounds,
    )

    if _ran_in_week(config, now_local):
        return False
    slot = weekly_fire_slot(config, now_local)
    if slot is None or now_local < slot:
        return False
    monday = now_local.date() - timedelta(days=now_local.weekday())
    if now_local.weekday() not in _eligible_days(config, monday):
        return False
    window_start, window_end = _window_bounds(config, now_local.date(), now_local.tzinfo)
    return window_start <= now_local <= window_end


def test_fires_exactly_once_across_the_week():
    """Sweeping the whole week minute-by-minute yields a single fire.

    This is the regression: the old rule was "once per configured day", so a
    Sunday+Tuesday schedule broadcast twice a week.
    """
    config = _config()
    fired_at = []

    moment = MONDAY
    end = MONDAY + timedelta(days=7)
    while moment < end:
        if _fires_on(config, moment):
            fired_at.append(moment)
            # Record the run the way trigger_rwt_broadcast does.
            config.last_run_at = moment.astimezone(timezone.utc)
            config.last_run_status = 'success'
        moment += timedelta(minutes=1)

    assert len(fired_at) == 1, f"expected one RWT this week, got {len(fired_at)}"
    assert _day_of(fired_at[0]) in (SUNDAY, TUESDAY)


def test_fires_again_the_following_week():
    """A run recorded last week does not suppress this week's test."""
    config = _config()
    last_week = MONDAY - timedelta(days=7)
    config.last_run_at = (
        weekly_fire_slot(config, last_week).astimezone(timezone.utc)
    )
    config.last_run_status = 'success'

    slot = weekly_fire_slot(config, MONDAY)
    assert week_key(slot) != week_key(last_week)
    assert _fires_on(config, slot) is True


def test_does_not_fire_before_the_slot():
    config = _config()
    slot = weekly_fire_slot(config, MONDAY)
    assert _fires_on(config, slot - timedelta(minutes=1)) is False


def _week_with_a_catch_up_day(config):
    """Find a reference week whose slot has a later allowed day after it.

    The slot day is drawn per week, so scan forward rather than hard-coding a
    week and skipping when the draw is inconvenient.
    """
    for offset in range(20):
        reference = MONDAY + timedelta(weeks=offset)
        slot = weekly_fire_slot(config, reference)
        if slot is not None and slot.weekday() < 6:
            return reference, slot
    raise AssertionError("no week produced a slot with a later day")


def test_missed_slot_is_caught_up_on_a_later_allowed_day():
    """A slot missed while the station was down still fires later that week."""
    # All seven days allowed, so there is always a later day to catch up on.
    config = _config(days=(0, 1, 2, 3, 4, 5, 6))
    _reference, slot = _week_with_a_catch_up_day(config)

    # Next allowed day, inside the window: the test still goes out.
    catch_up = (slot + timedelta(days=1)).replace(hour=9, minute=0)
    assert _fires_on(config, catch_up) is True


def test_does_not_fire_outside_the_window_after_a_missed_slot():
    """Catch-up is bounded by the configured window, not "any time later"."""
    config = _config(days=(0, 1, 2, 3, 4, 5, 6))
    _reference, slot = _week_with_a_catch_up_day(config)

    after_hours = (slot + timedelta(days=1)).replace(hour=22, minute=0)
    assert _fires_on(config, after_hours) is False


# ---------------------------------------------------------------------------
# compute_next_fire (drives the UI's "next scheduled fire")
# ---------------------------------------------------------------------------


def test_next_fire_reports_this_weeks_slot_when_upcoming():
    config = _config()
    slot = weekly_fire_slot(config, MONDAY)
    assert compute_next_fire(config, slot - timedelta(hours=1)) == slot


def test_next_fire_rolls_to_next_week_once_sent():
    config = _config()
    slot = weekly_fire_slot(config, MONDAY)
    config.last_run_at = slot.astimezone(timezone.utc)
    config.last_run_status = 'success'

    nxt = compute_next_fire(config, slot + timedelta(hours=1))
    assert nxt is not None
    assert week_key(nxt) == week_key(MONDAY + timedelta(days=7))
    assert _day_of(nxt) in (SUNDAY, TUESDAY)


def test_next_fire_is_none_when_disabled():
    assert compute_next_fire(_config(enabled=False), MONDAY) is None


def test_next_fire_survives_a_skip_spanning_the_whole_week():
    """A skip covering every allowed day rolls forward, not to None."""
    config = _config(skip_until=(MONDAY + timedelta(days=6)).date())
    nxt = compute_next_fire(config, MONDAY)
    assert nxt is not None
    assert nxt.date() > config.skip_until


# ---------------------------------------------------------------------------
# "Skip this week"
# ---------------------------------------------------------------------------


def test_skip_week_suppresses_every_remaining_day_in_the_week():
    """Skipping must clear the whole week, not just the next configured day.

    The old skip set skip_until to the day before the next configured weekday.
    Under weekly selection that was a no-op: with Sunday+Tuesday configured,
    skipping on a Monday left both Tuesday and Sunday eligible, so the test
    still landed on one of them.  Skipping now runs to the Sunday of the
    current ISO week.
    """
    monday = MONDAY.date()
    skip_until = monday + timedelta(days=6 - monday.weekday())  # what the route sets
    config = _config(skip_until=skip_until)

    assert weekly_fire_slot(config, MONDAY) is None

    # And the schedule resumes the following week.
    nxt = compute_next_fire(config, MONDAY)
    assert nxt is not None
    assert nxt.date() > skip_until
    assert _day_of(nxt) in (SUNDAY, TUESDAY)
