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
API Routes for Stream Profile Management

Provides REST API for managing Icecast stream profiles:
- GET /api/stream-profiles - List all profiles
- GET /api/stream-profiles/<name> - Get specific profile
- POST /api/stream-profiles - Create new profile
- PUT /api/stream-profiles/<name> - Update profile
- DELETE /api/stream-profiles/<name> - Delete profile
- POST /api/stream-profiles/<name>/enable - Enable profile
- POST /api/stream-profiles/<name>/disable - Disable profile
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from flask import Flask, jsonify, render_template, request

from app_core.audio.stream_profiles import (
    StreamProfile,
    StreamProfileManager,
    StreamQuality,
    get_stream_profile_manager,
)

logger = logging.getLogger(__name__)


def register(app: Flask, route_logger: logging.Logger) -> None:
    """Register stream profile API routes."""
    
    @app.route("/settings/stream-profiles")
    def stream_profiles_page() -> Any:
        """Render the stream profiles management page."""
        return render_template("stream_profiles.html")
    
    @app.route("/api/stream-profiles", methods=["GET"])
    def get_stream_profiles() -> Tuple[Any, int]:
        """Get all stream profiles."""
        try:
            manager = get_stream_profile_manager()
            profiles = manager.get_all_profiles()
            
            return jsonify({
                "success": True,
                "profiles": {name: profile.to_dict() for name, profile in profiles.items()},
                "active_count": len(manager.get_active_profiles()),
                "total_count": len(profiles)
            }), 200
        
        except Exception as e:
            route_logger.error(f"Error getting stream profiles: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    @app.route("/api/stream-profiles/<name>", methods=["GET"])
    def get_stream_profile(name: str) -> Tuple[Any, int]:
        """Get a specific stream profile."""
        try:
            manager = get_stream_profile_manager()
            profile = manager.get_profile(name)
            
            if not profile:
                return jsonify({
                    "success": False,
                    "error": f"Profile '{name}' not found"
                }), 404
            
            return jsonify({
                "success": True,
                "profile": profile.to_dict()
            }), 200
        
        except Exception as e:
            route_logger.error(f"Error getting stream profile '{name}': {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    @app.route("/api/stream-profiles", methods=["POST"])
    def create_stream_profile() -> Tuple[Any, int]:
        """Create a new stream profile."""
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({
                    "success": False,
                    "error": "No data provided"
                }), 400
            
            # Check if using a preset
            if "preset" in data:
                manager = get_stream_profile_manager()
                
                try:
                    quality = StreamQuality(data["preset"])
                except ValueError:
                    return jsonify({
                        "success": False,
                        "error": f"Invalid preset '{data['preset']}'. Valid: low, medium, high, premium"
                    }), 400
                
                profile = manager.create_profile_from_preset(
                    name=data["name"],
                    quality=quality,
                    mount=data.get("mount")
                )
            else:
                # Create from full specification
                try:
                    profile = StreamProfile.from_dict(data)
                except TypeError as e:
                    return jsonify({
                        "success": False,
                        "error": f"Invalid profile data: {e}"
                    }), 400
            
            # Save profile
            manager = get_stream_profile_manager()
            if manager.save_profile(profile):
                return jsonify({
                    "success": True,
                    "profile": profile.to_dict(),
                    "message": f"Profile '{profile.name}' created successfully"
                }), 201
            else:
                return jsonify({
                    "success": False,
                    "error": "Failed to save profile"
                }), 500
        
        except Exception as e:
            route_logger.error(f"Error creating stream profile: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    @app.route("/api/stream-profiles/<name>", methods=["PUT"])
    def update_stream_profile(name: str) -> Tuple[Any, int]:
        """Update an existing stream profile."""
        try:
            manager = get_stream_profile_manager()
            
            # Check if profile exists
            existing = manager.get_profile(name)
            if not existing:
                return jsonify({
                    "success": False,
                    "error": f"Profile '{name}' not found"
                }), 404
            
            data = request.get_json()
            if not data:
                return jsonify({
                    "success": False,
                    "error": "No data provided"
                }), 400
            
            # Ensure name matches
            data["name"] = name
            
            try:
                profile = StreamProfile.from_dict(data)
            except TypeError as e:
                return jsonify({
                    "success": False,
                    "error": f"Invalid profile data: {e}"
                }), 400
            
            if manager.save_profile(profile):
                return jsonify({
                    "success": True,
                    "profile": profile.to_dict(),
                    "message": f"Profile '{name}' updated successfully"
                }), 200
            else:
                return jsonify({
                    "success": False,
                    "error": "Failed to save profile"
                }), 500
        
        except Exception as e:
            route_logger.error(f"Error updating stream profile '{name}': {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    @app.route("/api/stream-profiles/<name>", methods=["DELETE"])
    def delete_stream_profile(name: str) -> Tuple[Any, int]:
        """Delete a stream profile."""
        try:
            manager = get_stream_profile_manager()
            
            if manager.delete_profile(name):
                return jsonify({
                    "success": True,
                    "message": f"Profile '{name}' deleted successfully"
                }), 200
            else:
                return jsonify({
                    "success": False,
                    "error": f"Profile '{name}' not found or could not be deleted"
                }), 404
        
        except Exception as e:
            route_logger.error(f"Error deleting stream profile '{name}': {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    @app.route("/api/stream-profiles/<name>/enable", methods=["POST"])
    def enable_stream_profile(name: str) -> Tuple[Any, int]:
        """Enable a stream profile."""
        try:
            manager = get_stream_profile_manager()
            
            if manager.enable_profile(name):
                return jsonify({
                    "success": True,
                    "message": f"Profile '{name}' enabled successfully"
                }), 200
            else:
                return jsonify({
                    "success": False,
                    "error": f"Profile '{name}' not found"
                }), 404
        
        except Exception as e:
            route_logger.error(f"Error enabling stream profile '{name}': {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    @app.route("/api/stream-profiles/<name>/disable", methods=["POST"])
    def disable_stream_profile(name: str) -> Tuple[Any, int]:
        """Disable a stream profile."""
        try:
            manager = get_stream_profile_manager()
            
            if manager.disable_profile(name):
                return jsonify({
                    "success": True,
                    "message": f"Profile '{name}' disabled successfully"
                }), 200
            else:
                return jsonify({
                    "success": False,
                    "error": f"Profile '{name}' not found"
                }), 404
        
        except Exception as e:
            route_logger.error(f"Error disabling stream profile '{name}': {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    @app.route("/api/stream-profiles/bandwidth-estimate", methods=["GET"])
    def get_bandwidth_estimate() -> Tuple[Any, int]:
        """Get bandwidth estimate for active profiles."""
        try:
            manager = get_stream_profile_manager()
            
            # Get duration from query params (default 3600 seconds = 1 hour)
            duration = int(request.args.get("duration", 3600))
            
            total_bandwidth = manager.get_total_bandwidth_estimate(duration)
            
            # Get per-profile estimates
            profile_estimates = {}
            for profile in manager.get_active_profiles():
                profile_estimates[profile.name] = {
                    "bitrate_kbps": profile.bitrate,
                    "estimated_mb": profile.estimate_bandwidth(duration)
                }
            
            return jsonify({
                "success": True,
                "duration_seconds": duration,
                "total_mb": total_bandwidth,
                "profiles": profile_estimates
            }), 200
        
        except Exception as e:
            route_logger.error(f"Error estimating bandwidth: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500


__all__ = ["register"]
