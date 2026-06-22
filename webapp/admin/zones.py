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

NOAA zone catalog management routes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Any

from flask import Blueprint, jsonify, render_template, request, current_app
from werkzeug.utils import secure_filename

from app_core.extensions import db
from app_core.models import NWSZone
from app_core.zones import ensure_zone_catalog, clear_zone_lookup_cache, get_zone_lookup
from app_core.auth.roles import require_permission
from app_utils.zone_catalog import iter_zone_records, detect_zone_schema


def _get_zone_catalog_path() -> Path:
    """Get the zone catalog path using smart resolution.
    
    Priority order:
    1. NWS_ZONE_DBF_PATH from app config (if set and exists)
    2. Auto-detect any .dbf file in assets/ directory
    3. Fall back to default assets/z_18mr25.dbf (may not exist)
    """
    config_path = current_app.config.get('NWS_ZONE_DBF_PATH')
    
    if config_path:
        config_path_obj = Path(config_path)
        if config_path_obj.exists():
            return config_path_obj
    
    # Auto-detect: look for any .dbf file in assets directory
    assets_dir = Path("assets")
    if assets_dir.exists() and assets_dir.is_dir():
        dbf_files = sorted(assets_dir.glob("*.dbf"), reverse=True)
        if dbf_files:
            return dbf_files[0]
    
    # Fall back to default
    return Path("assets/z_18mr25.dbf")


logger = logging.getLogger(__name__)

# Create Blueprint for zone management routes
zones_bp = Blueprint('zones_admin', __name__)


@zones_bp.route('/zones')
@require_permission('system.configure')
def zone_management():
    """Display zone catalog management page."""
    try:
        # Get current zone catalog info using smart path resolution
        zone_path = _get_zone_catalog_path()
        zone_exists = zone_path.exists()
        
        # Get zone statistics
        zone_count = NWSZone.query.count()
        
        # Get zone lookup cache status
        zone_lookup = get_zone_lookup()
        cached_count = len(zone_lookup)
        
        return render_template(
            'admin/zones.html',
            zone_path=str(zone_path),
            zone_exists=zone_exists,
            zone_count=zone_count,
            cached_count=cached_count,
        )
    except Exception as e:
        logger.error(f"Error loading zone management page: {e}")
        # Use smart path resolution for error case too
        fallback_path = _get_zone_catalog_path()
        return render_template(
            'admin/zones.html',
            zone_path=str(fallback_path),
            zone_exists=fallback_path.exists(),
            zone_count=0,
            cached_count=0,
            error=str(e)
        )


@zones_bp.route('/zones/info', methods=['GET'])
@require_permission('system.configure')
def zone_info():
    """Get zone catalog information."""
    try:
        zone_path = _get_zone_catalog_path()
        zone_exists = zone_path.exists()
        
        info = {
            'path': str(zone_path),
            'exists': zone_exists,
            'db_count': NWSZone.query.count(),
            'cache_count': len(get_zone_lookup()),
        }
        
        if zone_exists:
            info['file_size'] = zone_path.stat().st_size
            info['file_size_mb'] = round(zone_path.stat().st_size / 1024 / 1024, 2)
            
            # Try to count records in DBF file
            try:
                records = list(iter_zone_records(zone_path))
                info['dbf_record_count'] = len(records)
            except Exception as e:
                logger.warning(f"Could not read DBF file: {e}")
                info['dbf_record_count'] = None
        
        return jsonify(info)
    except Exception as e:
        logger.error(f"Error getting zone info: {e}")
        return jsonify({'error': str(e)}), 500


@zones_bp.route('/zones/reload', methods=['POST'])
@require_permission('system.configure')
def reload_zones():
    """Reload zone catalog from DBF file into database."""
    try:
        # Clear cache first
        clear_zone_lookup_cache()
        
        # Reload from file. Scope deletions to public so an operator
        # clicking "Reload from File" against the bundled public-zone
        # DBF refreshes the public catalog without wiping marine zones
        # that were uploaded separately via the upload form.
        success = ensure_zone_catalog(logger, delete_scope="public")
        
        if success:
            zone_count = NWSZone.query.count()
            return jsonify({
                'success': True,
                'message': f'Zone catalog reloaded successfully. {zone_count} zones loaded.',
                'zone_count': zone_count
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to reload zone catalog. Check logs for details.'
            }), 500
            
    except Exception as e:
        logger.error(f"Error reloading zone catalog: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@zones_bp.route('/zones/upload', methods=['POST'])
@require_permission('system.configure')
def upload_zone_file():
    """Upload a new zone catalog DBF file."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Validate file extension
        if not file.filename.lower().endswith('.dbf'):
            return jsonify({'error': 'File must be a .dbf file'}), 400

        # Use secure filename; reject if it sanitises to empty
        filename = secure_filename(file.filename)
        if not filename:
            return jsonify({'error': 'Invalid filename'}), 400

        # Get upload directory (assets folder), resolved against the app root
        # so it works regardless of the current working directory.
        upload_dir = Path(current_app.root_path) / 'assets'
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        # Save the file
        file_path = upload_dir / filename
        file.save(str(file_path))
        
        logger.info(f"Zone catalog file uploaded: {file_path}")

        # Detect schema so we can report it back to the operator. The
        # admin UI advertises support for public + marine + offshore
        # DBFs, all of which can be layered without overwriting each
        # other — uploads are purely additive (delete_scope=False).
        # detect_zone_schema raises ValueError on an unsupported DBF,
        # which the outer except handler reports to the user.
        try:
            schema = detect_zone_schema(file_path)
        except Exception:
            schema = "public"  # Treat ambiguous DBFs as public so legacy uploads still work.

        # Only update NWS_ZONE_DBF_PATH for public-zone uploads; the
        # marine catalog is additive and shouldn't replace the primary
        # public-zone source on next restart.
        if schema == "public":
            current_app.config['NWS_ZONE_DBF_PATH'] = str(file_path)

        clear_zone_lookup_cache()
        success = ensure_zone_catalog(
            logger, source_path=file_path, delete_scope=False
        )

        if success:
            zone_count = NWSZone.query.count()
            return jsonify({
                'success': True,
                'message': (
                    f'File uploaded ({schema} zones) and merged into '
                    f'catalog. Total zones now: {zone_count}.'
                ),
                'path': str(file_path),
                'schema': schema,
                'zone_count': zone_count,
            })
        else:
            return jsonify({
                'success': True,
                'message': 'File uploaded but failed to load zones. Check file format.',
                'path': str(file_path),
                'schema': schema,
                'warning': 'Zone loading failed',
            })
            
    except Exception as e:
        logger.exception("Error uploading zone file")
        try:
            db.session.rollback()
        except Exception:
            logger.exception("Rollback after upload failure also failed")
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500


@zones_bp.route('/zones/search', methods=['GET'])
@require_permission('system.configure')
def search_zones():
    """Search zones by code or name."""
    try:
        query = request.args.get('q', '').strip().upper()
        limit = int(request.args.get('limit', 50))
        
        if not query:
            return jsonify({'zones': []})
        
        # Search by zone code or name
        zones = NWSZone.query.filter(
            db.or_(
                NWSZone.zone_code.ilike(f'%{query}%'),
                NWSZone.name.ilike(f'%{query}%'),
                NWSZone.state_code.ilike(f'%{query}%')
            )
        ).limit(limit).all()
        
        result = [{
            'zone_code': z.zone_code,
            'name': z.name,
            'state_code': z.state_code,
            'cwa': z.cwa,
            'time_zone': z.time_zone,
            'latitude': z.latitude,
            'longitude': z.longitude
        } for z in zones]
        
        return jsonify({'zones': result})
        
    except Exception as e:
        logger.error(f"Error searching zones: {e}")
        return jsonify({'error': str(e)}), 500


logger.info("Zone management routes registered")
