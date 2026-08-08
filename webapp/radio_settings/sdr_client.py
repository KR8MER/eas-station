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

"""Talking to the SDR hardware service over Redis."""

import json
import time
import uuid
from typing import Any, Dict

from . import deps


def _send_sdr_command(action: str, **kwargs) -> Dict[str, Any]:
    """Send a command to the sdr-service via Redis and wait for response."""
    try:
        redis_client = deps.get_redis_client()
        command_id = str(uuid.uuid4())
        
        command = {
            "action": action,
            "command_id": command_id,
            **kwargs
        }
        
        redis_client.rpush("sdr:commands", json.dumps(command))
        
        # Wait for result (5s timeout)
        start_time = time.time()
        while time.time() - start_time < 5.0:
            result_json = redis_client.get(f"sdr:command_result:{command_id}")
            if result_json:
                return json.loads(result_json)
            time.sleep(0.1)
            
        return {"success": False, "error": "Timeout waiting for sdr-service"}
        
    except Exception as e:
        return {"success": False, "error": str(e)}


__all__ = [
    "_send_sdr_command",
]
