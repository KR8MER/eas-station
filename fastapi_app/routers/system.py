"""
System API Router - FastAPI implementation
Provides endpoints for system health and status monitoring
"""

import logging
from datetime import datetime

import psutil
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.database import get_db
from fastapi_app.schemas.system import (
    HealthCheckResponse,
    SystemStatusResponse,
    SystemResourcesResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthCheckResponse)
async def health_check(
    db: AsyncSession = Depends(get_db)
):
    """
    System health check endpoint.

    Returns the current health status of the application and its dependencies.
    This endpoint is used by load balancers and monitoring systems.
    """
    checks = {}

    # Check database connectivity
    try:
        await db.execute("SELECT 1")
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # TODO: Check Redis connectivity
    # TODO: Check audio service connectivity

    # Determine overall status
    all_healthy = all(checks.values())
    status = "healthy" if all_healthy else "degraded" if any(checks.values()) else "unhealthy"

    return HealthCheckResponse(
        status=status,
        version="3.0.0-alpha",
        timestamp=datetime.utcnow(),
        checks=checks
    )


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(
    db: AsyncSession = Depends(get_db)
):
    """
    Get comprehensive system status.

    Returns detailed system information including resource usage,
    service status, and health metrics.
    """
    # Get resource usage
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    uptime = psutil.boot_time()

    resources = SystemResourcesResponse(
        cpu_percent=cpu_percent,
        memory_percent=memory.percent,
        memory_available_mb=memory.available / (1024 * 1024),
        disk_percent=disk.percent,
        disk_available_gb=disk.free / (1024 * 1024 * 1024),
        uptime_seconds=(datetime.utcnow().timestamp() - uptime)
    )

    # Get health check
    health = await health_check(db)

    # TODO: Get service statuses
    services = {
        "audio_service": "unknown",
        "flask_app": "running",  # Assuming Flask is still running alongside
        "redis": "unknown",
        "database": "healthy" if health.checks.get("database") else "unhealthy"
    }

    return SystemStatusResponse(
        health=health,
        resources=resources,
        services=services,
        timestamp=datetime.utcnow()
    )


@router.get("/resources", response_model=SystemResourcesResponse)
async def get_system_resources():
    """
    Get system resource usage.

    Returns current CPU, memory, and disk usage metrics.
    """
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    uptime = psutil.boot_time()

    return SystemResourcesResponse(
        cpu_percent=cpu_percent,
        memory_percent=memory.percent,
        memory_available_mb=memory.available / (1024 * 1024),
        disk_percent=disk.percent,
        disk_available_gb=disk.free / (1024 * 1024 * 1024),
        uptime_seconds=(datetime.utcnow().timestamp() - uptime)
    )
