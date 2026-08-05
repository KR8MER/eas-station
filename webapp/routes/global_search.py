"""Global identifier search — one box, smart routing.

Routes operators from a single query box to the right destination
without making them think about which page hosts which data.  Tries
exact correlation-ID matches first (they're the most precise), then
DB row IDs, then partial matches; finally falls through to the
``/logs?search=...`` text search.

This is the navigation answer to the question "where did that alert
go?" — you paste the identifier into the navbar box, you land on its
trail.
"""
from __future__ import annotations

from urllib.parse import urlencode, quote

from flask import Flask, abort, redirect, render_template, request, url_for
from sqlalchemy import or_

from app_core.extensions import db
from app_core.models import (
    CAPAlert,
    EASMessage,
    ManualEASActivation,
    ReceivedEASAlert,
)


# Hard cap on the query string we're willing to look at.  Anything
# longer is almost certainly garbage (pasted log line, accidental
# clipboard contents) and only burns DB time.
_MAX_QUERY_LEN = 255


def _exact_alert_trail_redirect(identifier: str):
    """If *identifier* matches anything we know how to put on a trail,
    return a redirect response to that trail page.  Else return None."""
    # CAPAlert.identifier is the canonical correlation key.
    if CAPAlert.query.filter_by(identifier=identifier).first():
        return redirect(f"/alerts/{quote(identifier, safe='')}/trail", code=302)
    # OTA-derived identifiers don't have a CAPAlert row but do appear
    # on EASMessage.alert_identifier (when the migration has stamped
    # them) or as ManualEASActivation.identifier.
    if EASMessage.query.filter_by(alert_identifier=identifier).first():
        return redirect(f"/alerts/{quote(identifier, safe='')}/trail", code=302)
    if ManualEASActivation.query.filter_by(identifier=identifier).first():
        return redirect(f"/alerts/{quote(identifier, safe='')}/trail", code=302)
    return None


def _numeric_alert_detail_redirect(query: str):
    """If *query* is a pure integer that matches a CAPAlert row id,
    redirect to that alert's detail page.  Else return None."""
    if not query.isdigit():
        return None
    try:
        alert_id = int(query)
    except ValueError:
        return None
    alert = CAPAlert.query.get(alert_id)
    if alert is None:
        return None
    return redirect(f"/alerts/{alert_id}", code=302)


def _partial_identifier_matches(query: str, limit: int = 10):
    """Return a list of (identifier, label) tuples whose identifier
    contains *query* as a substring.  Used to populate the
    disambiguation page when no exact match wins."""
    like = f"%{query}%"
    rows = (
        CAPAlert.query
        .filter(CAPAlert.identifier.ilike(like))
        .order_by(CAPAlert.sent.desc())
        .limit(limit)
        .all()
    )
    out = [
        {
            "identifier": r.identifier,
            "label": r.event or "(no event)",
            "sent": r.sent,
            "kind": "cap",
        }
        for r in rows
    ]
    # Also try the EASMessage alert_identifier column to surface
    # OTA-derived correlation IDs.
    eas_rows = (
        # without_audio(): search only reads alert_identifier.
        EASMessage.without_audio()
        .filter(EASMessage.alert_identifier.ilike(like))
        .order_by(EASMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    seen = {x["identifier"] for x in out}
    for m in eas_rows:
        if m.alert_identifier and m.alert_identifier not in seen:
            seen.add(m.alert_identifier)
            out.append({
                "identifier": m.alert_identifier,
                "label": f"EAS broadcast: {m.same_header or '(no SAME)'}",
                "sent": m.created_at,
                "kind": "ota",
            })
    return out


def register(app: Flask, logger) -> None:
    """Register the global search endpoint."""

    route_logger = logger.getChild("global_search")

    @app.route("/search")
    def global_search():
        query = (request.args.get("q") or "").strip()
        if not query:
            # Empty submit — bounce back to home rather than rendering
            # an "all alerts" dump.
            # `url_for("index")` would work, but the home route is a stable
            # public URL and this keeps the redirect free of endpoint coupling.
            return redirect("/", code=302)
        if len(query) > _MAX_QUERY_LEN:
            query = query[:_MAX_QUERY_LEN]

        # 1. Direct correlation-ID hit anywhere.
        try:
            hit = _exact_alert_trail_redirect(query)
        except Exception as exc:
            route_logger.warning("exact-match lookup failed: %s", exc)
            try:
                db.session.rollback()
            except Exception:
                pass
            hit = None
        if hit is not None:
            return hit

        # 2. Numeric → alert detail (the integer DB-id flow operators
        # use when they're reading SQL output).
        try:
            hit = _numeric_alert_detail_redirect(query)
        except Exception as exc:
            route_logger.warning("numeric-id lookup failed: %s", exc)
            try:
                db.session.rollback()
            except Exception:
                pass
            hit = None
        if hit is not None:
            return hit

        # 3. Partial substring across identifiers — if exactly one
        # alert matches we still go straight to its trail.  Multiple
        # matches render a small disambiguation page.
        try:
            matches = _partial_identifier_matches(query, limit=10)
        except Exception as exc:
            route_logger.warning("partial-match lookup failed: %s", exc)
            try:
                db.session.rollback()
            except Exception:
                pass
            matches = []

        if len(matches) == 1:
            return redirect(
                f"/alerts/{quote(matches[0]['identifier'], safe='')}/trail",
                code=302,
            )

        if matches:
            return render_template(
                "search/results.html",
                query=query,
                matches=matches,
                logs_fallback_url=f"/logs?type=all&{urlencode({'search': query})}",
            )

        # 4. Nothing identifier-shaped matched — fall through to the
        # logs text search.  Operators expect their query to find
        # *something* if anything mentions it.
        return redirect(
            f"/logs?type=all&{urlencode({'search': query})}",
            code=302,
        )


__all__ = ["register"]
