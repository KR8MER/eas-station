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

"""Boundary metadata helpers used by the NOAA alerts application."""

import math
import re
from typing import Dict, List, Optional, Tuple


BOUNDARY_GROUP_LABELS = {
    "geographic": "Geographic Boundaries",
    "service": "Service Boundaries",
    "infrastructure": "Infrastructure",
    "hydrography": "Water Features",
    "custom": "Custom Layers",
    "unknown": "Uncategorized Boundaries",
}

BOUNDARY_TYPE_CONFIG = {
    "county": {
        "label": "Counties",
        "group": "geographic",
        "color": "#6c757d",
        "aliases": ["counties"],
    },
    "township": {
        "label": "Townships",
        "group": "geographic",
        "color": "#28a745",
        "aliases": ["townships"],
    },
    "villages": {
        "label": "Villages",
        "group": "geographic",
        "color": "#17a2b8",
        "aliases": ["village"],
    },
    "fire": {
        "label": "Fire Districts",
        "group": "service",
        "color": "#dc3545",
        "aliases": ["fire_districts"],
    },
    "ems": {
        "label": "EMS Districts",
        "group": "service",
        "color": "#007bff",
        "aliases": ["ems_districts"],
    },
    "school": {
        "label": "School Districts",
        "group": "service",
        "color": "#ffc107",
        "aliases": ["school_districts"],
    },
    "electric": {
        "label": "Electric Utilities",
        "group": "infrastructure",
        "color": "#fd7e14",
        "aliases": ["electric_utilities"],
    },
    "telephone": {
        "label": "Telephone Service",
        "group": "infrastructure",
        "color": "#6f42c1",
        "aliases": ["telephone_service"],
    },
    "railroads": {
        "label": "Railroads",
        "group": "infrastructure",
        "color": "#b45309",
        "aliases": ["railroad", "rail", "railway", "railways", "rails"],
    },
    "rivers": {
        "label": "Rivers & Streams",
        "group": "hydrography",
        "color": "#0ea5e9",
        "aliases": ["river", "streams", "stream", "creeks", "creek", "waterways", "waterway"],
    },
    "waterbodies": {
        "label": "Lakes & Ponds",
        "group": "hydrography",
        "color": "#2563eb",
        "aliases": ["lakes", "lake", "ponds", "pond", "reservoirs", "reservoir"],
    },
}


def normalize_boundary_type(value: Optional[str]) -> str:
    if value is None:
        return "unknown"

    sanitized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")

    if not sanitized:
        return "unknown"

    for key, config in BOUNDARY_TYPE_CONFIG.items():
        aliases = {key}
        aliases.update(config.get("aliases", []))
        if sanitized in aliases:
            return key

    return sanitized


def get_boundary_display_label(boundary_type: Optional[str]) -> str:
    normalized = normalize_boundary_type(boundary_type)
    if normalized in BOUNDARY_TYPE_CONFIG:
        return BOUNDARY_TYPE_CONFIG[normalized]["label"]

    if normalized in {"unknown", ""}:
        return "Unknown Boundary"

    return normalized.replace("_", " ").title()


def get_boundary_group(boundary_type: Optional[str]) -> str:
    normalized = normalize_boundary_type(boundary_type)
    return BOUNDARY_TYPE_CONFIG.get(normalized, {}).get("group", "custom")


def get_boundary_color(boundary_type: Optional[str]) -> Optional[str]:
    normalized = normalize_boundary_type(boundary_type)
    return BOUNDARY_TYPE_CONFIG.get(normalized, {}).get("color")


def get_field_mappings() -> Dict[str, Dict[str, List[str]]]:
    return {
        "electric": {
            "name_fields": ["COMPNAME", "Company", "Provider", "Utility"],
            "description_fields": ["COMPCODE", "COMPTYPE", "Shape_Leng", "SHAPE_STAr"],
        },
        "villages": {
            "name_fields": ["CORPORATIO", "VILLAGE", "NAME", "Municipality"],
            "description_fields": ["POP_2020", "POP_2010", "POP_2000", "SQMI"],
        },
        "school": {
            "name_fields": ["District", "DISTRICT", "SCHOOL_DIS", "NAME"],
            "description_fields": ["STUDENTS", "Shape_Area", "ENROLLMENT"],
        },
        "fire": {
            "name_fields": ["DEPT", "DEPARTMENT", "STATION", "FIRE_DEPT"],
            "description_fields": ["STATION_NUM", "TYPE", "SERVICE_AREA"],
        },
        "ems": {
            "name_fields": ["DEPT", "DEPARTMENT", "SERVICE", "PROVIDER"],
            "description_fields": ["STATION", "Area", "Shape_Area", "SERVICE_TYPE"],
        },
        "township": {
            "name_fields": ["TOWNSHIP_N", "TOWNSHIP", "TWP_NAME", "NAME"],
            "description_fields": ["POPULATION", "AREA_SQMI", "POP_2010", "COUNTY_COD"],
        },
        "telephone": {
            "name_fields": ["TELNAME", "PROVIDER", "COMPANY", "TELECOM", "CARRIER"],
            "description_fields": ["TELCO", "NAME", "LATA", "SERVICE_TYPE"],
        },
        "county": {
            "name_fields": ["COUNTY", "COUNTY_NAME", "NAME"],
            "description_fields": ["FIPS_CODE", "POPULATION", "AREA_SQMI"],
        },
        "railroads": {
            "name_fields": ["FULLNAME", "RAILROAD", "NAME"],
            "description_fields": ["LINEARID", "MTFCC", "ShapeSTLength"],
        },
        "rivers": {
            "name_fields": ["FULLNAME", "NAME", "GNIS_NAME"],
            "description_fields": ["LINEARID", "MTFCC", "GNIS_ID", "Shape_Leng"],
        },
        "waterbodies": {
            "name_fields": ["FULLNAME", "NAME", "GNIS_NAME"],
            "description_fields": ["HYDROID", "MTFCC", "GNIS_ID", "AWATER", "Shape_Area"],
        },
    }


def extract_name_and_description(properties: Dict[str, object], boundary_type: str) -> Tuple[str, str]:
    mappings = get_field_mappings()
    type_mapping = mappings.get(boundary_type, {})

    name = None
    for field in type_mapping.get("name_fields", []):
        if field in properties and properties[field]:
            name = str(properties[field]).strip()
            break

    if not name:
        name = str(properties.get("NAME") or properties.get("Name") or "Unnamed").strip()

    description_parts: List[str] = []
    for field in type_mapping.get("description_fields", []):
        if field in properties and properties[field] is not None:
            value = properties[field]
            if isinstance(value, (int, float)):
                if field.upper().startswith("POP"):
                    description_parts.append(f"Population {field[-4:]}: {value:,}")
                elif field == "AREA_SQMI":
                    description_parts.append(f"Area: {value:.2f} sq mi")
                elif field == "SQMI":
                    description_parts.append(f"Area: {value:.2f} sq mi")
                elif field == "Area":
                    description_parts.append(f"Area: {value:.2f} sq mi")
                elif field in ["Shape_Area", "SHAPE_STAr", "ShapeSTArea"]:
                    if "Area" in properties and properties["Area"]:
                        continue
                    sq_miles = value / 2589988.11
                    if sq_miles > 500:
                        sq_feet_to_sq_miles = value / 27878400
                        if sq_feet_to_sq_miles <= 500:
                            description_parts.append(f"Area: {sq_feet_to_sq_miles:.2f} sq mi")
                        else:
                            continue
                    else:
                        description_parts.append(f"Area: {sq_miles:.2f} sq mi")
                elif field == "STATION" and boundary_type == "ems":
                    description_parts.append(f"Station: {value}")
                elif field.upper() in ["SHAPE_LENG", "PERIMETER", "Shape_Length", "ShapeSTLength"]:
                    miles = value * 0.000621371
                    description_parts.append(f"Perimeter: {miles:.2f} miles")
                else:
                    description_parts.append(f"{field}: {value}")
            else:
                description_parts.append(f"{field}: {value}")

    for field in ["county_nam", "COUNTY", "County", "COUNTY_COD"]:
        if field in properties and properties[field]:
            description_parts.append(f"County: {properties[field]}")
            break

    description = "; ".join(description_parts) if description_parts else ""
    return name, description


def describe_mtfcc(code: Optional[str]) -> Optional[str]:
    if not code:
        return None

    mtfcc_descriptions = {
        "R1011": "Primary railroad line",
        "R1012": "Secondary railroad line",
        "R1051": "Railroad siding or yard",
    }

    return mtfcc_descriptions.get(code.upper(), None)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088

    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return radius_km * c


def calculate_linestring_length_km(coordinates: List[List[float]]) -> float:
    if not coordinates or len(coordinates) < 2:
        return 0.0

    total_km = 0.0
    for start, end in zip(coordinates[:-1], coordinates[1:]):
        if len(start) >= 2 and len(end) >= 2:
            lon1, lat1 = start[:2]
            lon2, lat2 = end[:2]
            total_km += haversine_distance(lat1, lon1, lat2, lon2)

    return total_km


def calculate_geometry_length_miles(geometry: Optional[dict]) -> Optional[float]:
    if not geometry or "type" not in geometry:
        return None

    geom_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    total_km = 0.0

    if geom_type == "LineString":
        total_km = calculate_linestring_length_km(coordinates)
    elif geom_type == "MultiLineString":
        for segment in coordinates:
            total_km += calculate_linestring_length_km(segment)
    elif geom_type == "Polygon":
        if coordinates:
            total_km = calculate_linestring_length_km(coordinates[0])
    elif geom_type == "MultiPolygon":
        for polygon in coordinates:
            if polygon:
                total_km += calculate_linestring_length_km(polygon[0])
    else:
        return None

    if total_km == 0:
        return None

    return total_km * 0.621371


__all__ = [
    "BOUNDARY_GROUP_LABELS",
    "BOUNDARY_TYPE_CONFIG",
    "calculate_geometry_length_miles",
    "calculate_linestring_length_km",
    "describe_mtfcc",
    "extract_name_and_description",
    "get_boundary_color",
    "get_boundary_display_label",
    "get_boundary_group",
    "get_field_mappings",
    "haversine_distance",
    "normalize_boundary_type",
]
