"""Backfill superseded_by_id gaps left by a vtec_action guard bug and a
vtec_year parsing gap.

The 20260402 backfill (20260402_backfill_vtec_superseded_alerts) linked every
VTEC chain at the time, but two bugs kept reopening gaps since then:

  1. poller/cap_poller.py::_insert_new_alert() guarded the call to
     _mark_vtec_chain_superseded() with
     ``if new_alert.vtec_action and new_alert.vtec_action != 'NEW':`` — a
     follow-on product whose vtec_action failed to parse (falsy) silently
     skipped linking its priors, with nothing to ever retry it. Fixed to
     only exclude an actual 'NEW' issuance.

  2. app_utils/vtec.py::extract_vtec_identity() derived vtec_year solely
     from the VTEC segment's begin/end times, both of which can be the
     all-zeros "ongoing" sentinel (000000T0000Z) on some CON/EXT products
     that omit both rather than restating the real one — observed on every
     KIWX Flood Warning CON/EXT product in this database. With no year,
     the chain key is incomplete and the alert can never be linked, by
     design (_mark_vtec_chain_superseded requires all five VTEC fields).
     Fixed to fall back to the CAP envelope's own `sent` timestamp when
     both VTEC times are the sentinel.

Fix #2 only helps alerts ingested after it lands — the ~41 existing rows
already have vtec_year NULL baked into their columns. This migration
re-derives it for them from their stored raw_json using the fixed parser,
then performs the same one-time superseded_by_id backfill as 20260402 for
every alert (of any vintage) that a complete VTEC key newly makes linkable.
The poller also runs a windowed version of the same link-repair every poll
cycle now (repair_vtec_chain_gaps) so any future gap self-heals; this
migration is the unwindowed, immediate version of that repair.

Both steps only ever fill a NULL column — an alert that already has a
vtec_year or a superseded_by_id (even one pointing past its immediate
neighbor, which is valid when a single follow-on had to close out more
than one still-open prior) is left untouched.

Revision ID: 20260817_repair_vtec_chain_gaps
Revises: 20260814_eas_dedup_settings
Create Date: 2026-08-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260817_repair_vtec_chain_gaps"
down_revision = "20260814_eas_dedup_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 0: re-derive vtec_year for rows the old begin/end-only parser
    # left NULL, using the same fallback logic now in
    # app_utils.vtec.extract_vtec_identity (both-sentinel VTEC times ->
    # the CAP envelope's `sent` year). Done in Python because the fallback
    # needs the real parser, not a SQL reimplementation of it.
    from app_utils.vtec import extract_vtec_identity

    conn = op.get_bind()
    candidates = conn.execute(
        sa.text(
            """
            SELECT id, raw_json
            FROM cap_alerts
            WHERE vtec_office IS NOT NULL
              AND vtec_etn    IS NOT NULL
              AND vtec_year   IS NULL
              AND raw_json    IS NOT NULL
            """
        )
    ).fetchall()

    repaired_years = 0
    for row in candidates:
        identity = extract_vtec_identity(row.raw_json)
        if not identity or identity.get("vtec_year") is None:
            continue
        conn.execute(
            sa.text("UPDATE cap_alerts SET vtec_year = :year WHERE id = :id"),
            {"year": identity["vtec_year"], "id": row.id},
        )
        repaired_years += 1

    if repaired_years:
        print(f"  -> re-derived vtec_year for {repaired_years} alert(s)")

    # Step 1: link every still-unlinked alert (now including the ones Step 0
    # just gave a year to) to its nearest newer sibling.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                LEAD(id) OVER (
                    PARTITION BY vtec_office,
                                 vtec_phenomenon,
                                 vtec_significance,
                                 vtec_etn,
                                 vtec_year
                    ORDER BY sent ASC, id ASC
                ) AS next_id
            FROM cap_alerts
            WHERE vtec_office       IS NOT NULL
              AND vtec_phenomenon   IS NOT NULL
              AND vtec_significance IS NOT NULL
              AND vtec_etn          IS NOT NULL
              AND vtec_year         IS NOT NULL
              AND superseded_by_id  IS NULL
        )
        UPDATE cap_alerts
        SET    superseded_by_id = ranked.next_id
        FROM   ranked
        WHERE  cap_alerts.id      = ranked.id
          AND  ranked.next_id     IS NOT NULL
        """
    )

    # Step 2: same terminal-close-out as 20260402 — a newly-backfilled link
    # whose superseder is itself a CAN/EXP means the prior alert's event is
    # definitively over and should drop out of the active-alerts view.
    op.execute(
        """
        UPDATE cap_alerts
        SET    expires = NOW(),
               status  = 'Expired'
        WHERE  superseded_by_id IS NOT NULL
          AND  status           != 'Expired'
          AND  (expires IS NULL OR expires > NOW())
          AND  EXISTS (
                   SELECT 1
                   FROM   cap_alerts superseder
                   WHERE  superseder.id          = cap_alerts.superseded_by_id
                     AND  superseder.vtec_action IN ('CAN', 'EXP')
               )
        """
    )


def downgrade() -> None:
    # Not reversible: no record of which vtec_year/superseded_by_id values
    # this migration set versus ones already present.
    pass
