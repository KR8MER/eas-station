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

from __future__ import annotations

"""The NOAA/NWS alerts API client used by the manual import.

Building a request, calling `api.weather.gov`, and the error type the routes
catch. The allow-list of query parameters is deliberate: the manual-import
form forwards user input into the query string, so anything not listed here is
dropped rather than passed through.
"""

import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import quote

import requests

from app_utils import UTC_TZ, get_location_timezone


# NOAA Weather API Configuration
# API Documentation: https://www.weather.gov/documentation/services-web-api
# Requirements:
# - User-Agent header with contact information (no API key required)
# - Accept header for response format (application/geo+json for CAP alerts)
NOAA_API_BASE_URL = "https://api.weather.gov/alerts"
NOAA_ALLOWED_QUERY_PARAMS = frozenset(
    {
        "area",
        "zone",
        "region",
        "region_type",
        "point",
        "start",
        "end",
        "event",
        "status",
        "message_type",
        "urgency",
        "severity",
        "certainty",
        "limit",
        "cursor",
    }
)
NOAA_USER_AGENT = os.environ.get(
    "NOAA_USER_AGENT",
    "EAS Station/2.12 (+https://github.com/KR8MER/eas-station; support@easstation.com)",
)

class NOAAImportError(Exception):
    """Raised when manual NOAA alert retrieval fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        query_url: Optional[str] = None,
        params: Optional[Dict[str, Union[str, int]]] = None,
        detail: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.query_url = query_url
        self.params = params
        self.detail = detail

def normalize_manual_import_datetime(value: Union[str, datetime, None]) -> Optional[datetime]:
    """Normalize manual import datetimes to UTC for consistent NOAA queries."""

    if value is None:
        return None
    if isinstance(value, datetime):
        dt_value = value
    else:
        raw_value = str(value).strip()
        if not raw_value:
            return None
        try:
            dt_value = datetime.fromisoformat(raw_value)
        except ValueError:
            try:
                dt_value = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
            except ValueError:
                return None
    if dt_value.tzinfo is None:
        dt_value = get_location_timezone().localize(dt_value)
    return dt_value.astimezone(UTC_TZ)

def format_noaa_timestamp(dt_value: Optional[datetime]) -> Optional[str]:
    """Render UTC timestamps in the NOAA API's preferred ISO format."""

    if not dt_value:
        return None
    return dt_value.astimezone(UTC_TZ).strftime("%Y-%m-%dT%H:%M:%SZ")

def build_noaa_alert_request(
    *,
    identifier: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    area: Optional[str] = None,
    event: Optional[str] = None,
    limit: int = 10,
) -> Tuple[str, Optional[Dict[str, Union[str, int]]]]:
    """Construct the NOAA alerts endpoint and query parameters for manual imports."""

    query_url = NOAA_API_BASE_URL
    params: Optional[Dict[str, Union[str, int]]] = None

    if identifier:
        encoded_identifier = quote(identifier.strip(), safe=":.")
        query_url = f"{NOAA_API_BASE_URL}/{encoded_identifier}.json"
    else:
        params = {}
        if start:
            formatted_start = format_noaa_timestamp(start)
            if formatted_start:
                params["start"] = formatted_start
        if end:
            formatted_end = format_noaa_timestamp(end)
            if formatted_end:
                params["end"] = formatted_end
        if area:
            params["area"] = area
        if event:
            params["event"] = event

        if params:
            params = {
                key: value
                for key, value in params.items()
                if key in NOAA_ALLOWED_QUERY_PARAMS and value is not None
            } or None
        else:
            params = None

    return query_url, params

def retrieve_noaa_alerts(
    *,
    identifier: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    area: Optional[str] = None,
    event: Optional[str] = None,
    limit: int = 10,
):
    """Execute a NOAA alerts query and return parsed features."""

    query_url, params = build_noaa_alert_request(
        identifier=identifier,
        start=start,
        end=end,
        area=area,
        event=event,
        limit=limit,
    )

    headers = {
        "Accept": "application/geo+json, application/json;q=0.9",
        "User-Agent": NOAA_USER_AGENT,
    }

    try:
        response = requests.get(query_url, params=params, headers=headers, timeout=20)
    except requests.RequestException as exc:
        raise NOAAImportError(
            f"Failed to retrieve NOAA alert data: {exc}",
            query_url=query_url,
            params=params,
        ) from exc

    final_url = response.url

    if response.status_code == 404:
        raise NOAAImportError(
            "No alert was found for the supplied identifier or filters.",
            status_code=404,
            query_url=final_url,
            params=params,
        )

    if response.status_code >= 400:
        error_detail: Optional[str] = None
        parameter_errors: Optional[List[str]] = None
        try:
            error_payload = response.json()
            if isinstance(error_payload, dict):
                error_detail = error_payload.get("detail") or error_payload.get("title")
                raw_parameter_errors = error_payload.get("parameterErrors")
                if isinstance(raw_parameter_errors, list):
                    formatted_errors = []
                    for item in raw_parameter_errors:
                        if isinstance(item, dict):
                            name = item.get("parameter")
                            message = item.get("message")
                            if name and message:
                                formatted_errors.append(f"{name}: {message}")
                    if formatted_errors:
                        parameter_errors = formatted_errors
        except ValueError:
            error_detail = response.text.strip() or None

        message = f"Failed to retrieve NOAA alert data: {response.status_code} {response.reason}"
        if error_detail:
            message = f"{message} ({error_detail})"
        if parameter_errors:
            message = f"{message} — {'; '.join(parameter_errors)}"

        raise NOAAImportError(
            message,
            status_code=response.status_code,
            query_url=final_url,
            params=params,
            detail=error_detail,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise NOAAImportError(
            "NOAA API response could not be decoded as JSON.",
            query_url=final_url,
            params=params,
        ) from exc

    if identifier:
        if isinstance(payload, dict) and "features" in payload:
            alerts_payloads = payload.get("features", []) or []
        else:
            alerts_payloads = [payload]
    else:
        alerts_payloads = payload.get("features", []) if isinstance(payload, dict) else []

    if not identifier:
        try:
            effective_limit = max(1, min(int(limit or 10), 50))
        except (TypeError, ValueError):
            effective_limit = 10
        alerts_payloads = alerts_payloads[:effective_limit]

    if not alerts_payloads:
        raise NOAAImportError(
            "NOAA API did not return any alerts for the provided criteria.",
            status_code=404,
            query_url=final_url,
            params=params,
        )

    return alerts_payloads, final_url, params
