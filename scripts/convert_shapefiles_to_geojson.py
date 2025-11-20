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

"""
Convert TIGER/Line shapefiles to GeoJSON format for boundary upload.

This script converts water boundary shapefiles (streams/rivers and ponds/lakes)
from the Census Bureau TIGER/Line format to GeoJSON, which can then be uploaded
via the admin interface at /admin/upload_boundaries.

Usage:
    python scripts/convert_shapefiles_to_geojson.py

The script processes:
    - tl_2010_39137_linearwater.shp  -> output/linearwater.geojson (rivers/streams)
    - tl_2010_39137_areawater.shp    -> output/areawater.geojson (lakes/ponds)
"""

import json
import os
import sys
from pathlib import Path

try:
    import shapefile
except ImportError:
    print("ERROR: pyshp library not installed.")
    print("Install it with: pip install pyshp==2.3.1")
    sys.exit(1)


def shapefile_to_geojson(shapefile_path, output_path):
    """
    Convert a shapefile to GeoJSON format.

    Args:
        shapefile_path: Path to the .shp file
        output_path: Path for the output .geojson file

    Returns:
        Dict with statistics about the conversion
    """
    print(f"\n{'='*70}")
    print(f"Converting: {shapefile_path}")
    print(f"Output: {output_path}")
    print(f"{'='*70}")

    # Read the shapefile
    sf = shapefile.Reader(shapefile_path)

    # Get field names
    fields = sf.fields[1:]  # Skip deletion flag field
    field_names = [field[0] for field in fields]

    print(f"\nFound {len(field_names)} attribute fields:")
    for i, name in enumerate(field_names, 1):
        print(f"  {i:2d}. {name}")

    # Convert to GeoJSON
    features = []
    shape_types = set()

    for shape_record in sf.shapeRecords():
        shape = shape_record.shape
        record = shape_record.record

        # Track shape types for reporting
        shape_types.add(shape.shapeTypeName)

        # Build properties from attributes
        properties = {}
        for i, field_name in enumerate(field_names):
            value = record[i]
            # Convert bytes to string if needed
            if isinstance(value, bytes):
                value = value.decode('utf-8', errors='ignore')
            properties[field_name] = value

        # Convert shape to GeoJSON geometry
        geometry = shape.__geo_interface__

        # Create GeoJSON feature
        feature = {
            "type": "Feature",
            "properties": properties,
            "geometry": geometry
        }
        features.append(feature)

    # Create GeoJSON FeatureCollection
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    # Write to file
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, indent=2)

    # Report statistics
    stats = {
        'feature_count': len(features),
        'shape_types': list(shape_types),
        'output_size_mb': os.path.getsize(output_path) / (1024 * 1024)
    }

    print(f"\n✓ Conversion complete!")
    print(f"  Features: {stats['feature_count']}")
    print(f"  Shape types: {', '.join(stats['shape_types'])}")
    print(f"  Output size: {stats['output_size_mb']:.2f} MB")

    # Show sample feature properties
    if features:
        print(f"\n  Sample feature properties:")
        sample = features[0]['properties']
        for key, value in list(sample.items())[:5]:
            print(f"    {key}: {value}")

    return stats


def main():
    """Main conversion process."""
    # Base directory
    base_dir = Path(__file__).parent.parent
    shapefile_dir = base_dir / "streams and ponds"
    output_dir = base_dir / "output" / "boundaries"

    print("\n" + "="*70)
    print("TIGER/Line Shapefile to GeoJSON Converter")
    print("For Putnam County (FIPS 39137) Water Boundaries")
    print("="*70)

    # Check if shapefile directory exists
    if not shapefile_dir.exists():
        print(f"\nERROR: Shapefile directory not found: {shapefile_dir}")
        sys.exit(1)

    # Define conversions
    conversions = [
        {
            'name': 'Linear Water Features (Rivers/Streams)',
            'shapefile': shapefile_dir / "tl_2010_39137_linearwater.shp",
            'output': output_dir / "linearwater.geojson",
            'boundary_type': 'rivers'
        },
        {
            'name': 'Area Water Features (Lakes/Ponds)',
            'shapefile': shapefile_dir / "tl_2010_39137_areawater.shp",
            'output': output_dir / "areawater.geojson",
            'boundary_type': 'waterbodies'
        }
    ]

    # Process each shapefile
    results = []
    for conv in conversions:
        if not conv['shapefile'].exists():
            print(f"\nWARNING: Shapefile not found: {conv['shapefile']}")
            continue

        try:
            stats = shapefile_to_geojson(
                str(conv['shapefile']),
                str(conv['output'])
            )
            stats['name'] = conv['name']
            stats['boundary_type'] = conv['boundary_type']
            stats['output_path'] = str(conv['output'])
            results.append(stats)
        except Exception as e:
            print(f"\nERROR converting {conv['name']}: {e}")
            import traceback
            traceback.print_exc()

    # Summary report
    print(f"\n\n{'='*70}")
    print("CONVERSION SUMMARY")
    print(f"{'='*70}")

    if results:
        for result in results:
            print(f"\n✓ {result['name']}")
            print(f"  Boundary type: {result['boundary_type']}")
            print(f"  Features: {result['feature_count']}")
            print(f"  Output: {result['output_path']}")

        print(f"\n\nNEXT STEPS:")
        print(f"{'='*70}")
        print("1. Upload the GeoJSON files via the admin web interface:")
        print("   Navigate to: /admin/upload_boundaries")
        print()
        print("2. For each file:")
        print("   - linearwater.geojson → Select boundary type: 'rivers'")
        print("   - areawater.geojson   → Select boundary type: 'waterbodies'")
        print()
        print("3. After upload, calculate intersections:")
        print("   Navigate to: /admin/calculate_all_intersections")
        print()
        print("4. View results:")
        print("   Check the boundaries table in the database")
        print("   View coverage reports in the admin dashboard")
        print(f"{'='*70}\n")
    else:
        print("\nNo files were converted successfully.")
        sys.exit(1)


if __name__ == '__main__':
    main()
