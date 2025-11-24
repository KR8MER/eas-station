"""
Pydantic schemas for System API endpoints
"""

from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class HealthCheckResponse(BaseModel):
    """Schema for health check response"""
    status: str = Field(..., description="Health status (healthy, degraded, unhealthy)")
    version: str = Field(..., description="Application version")
    timestamp: datetime = Field(..., description="Health check timestamp")
    checks: Dict[str, bool] = Field(default_factory=dict, description="Individual health checks")


class SystemResourcesResponse(BaseModel):
    """Schema for system resources"""
    cpu_percent: float = Field(..., description="CPU usage percentage", ge=0, le=100)
    memory_percent: float = Field(..., description="Memory usage percentage", ge=0, le=100)
    memory_available_mb: float = Field(..., description="Available memory in MB")
    disk_percent: float = Field(..., description="Disk usage percentage", ge=0, le=100)
    disk_available_gb: float = Field(..., description="Available disk space in GB")
    uptime_seconds: float = Field(..., description="System uptime in seconds")


class SystemStatusResponse(BaseModel):
    """Schema for comprehensive system status"""
    health: HealthCheckResponse
    resources: SystemResourcesResponse
    services: Dict[str, Any] = Field(..., description="Status of system services")
    timestamp: datetime = Field(..., description="Status timestamp")
