"""
Pydantic schemas for Alert API endpoints
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class AlertBase(BaseModel):
    """Base schema for alerts"""
    identifier: str = Field(..., description="Unique alert identifier")
    event: str = Field(..., description="Event type code")
    severity: str = Field(..., description="Alert severity (Extreme, Severe, Moderate, Minor, Unknown)")
    urgency: str = Field(..., description="Alert urgency (Immediate, Expected, Future, Past, Unknown)")
    certainty: str = Field(..., description="Alert certainty (Observed, Likely, Possible, Unlikely, Unknown)")


class AlertCreate(AlertBase):
    """Schema for creating a manual alert"""
    headline: str = Field(..., description="Alert headline", max_length=500)
    description: str = Field(..., description="Alert description", max_length=5000)
    instruction: Optional[str] = Field(None, description="Instructions for public", max_length=2000)
    area_desc: str = Field(..., description="Affected area description", max_length=500)
    onset: Optional[datetime] = Field(None, description="Expected onset time")
    expires: datetime = Field(..., description="Alert expiration time")


class AlertResponse(AlertBase):
    """Schema for alert response"""
    id: int = Field(..., description="Database ID")
    sender: Optional[str] = Field(None, description="Alert sender")
    sent: datetime = Field(..., description="Alert sent time")
    status: str = Field(..., description="Alert status (Actual, Exercise, System, Test, Draft)")
    msg_type: str = Field(..., description="Message type (Alert, Update, Cancel, Ack, Error)")
    scope: str = Field(..., description="Alert scope (Public, Restricted, Private)")
    headline: Optional[str] = Field(None, description="Alert headline")
    description: Optional[str] = Field(None, description="Alert description")
    instruction: Optional[str] = Field(None, description="Public instructions")
    area_desc: Optional[str] = Field(None, description="Affected area description")
    onset: Optional[datetime] = Field(None, description="Expected onset time")
    expires: Optional[datetime] = Field(None, description="Alert expiration time")
    effective: Optional[datetime] = Field(None, description="Effective time")
    category: Optional[str] = Field(None, description="Alert category")
    response_type: Optional[str] = Field(None, description="Recommended response")
    zones: Optional[List[str]] = Field(None, description="Affected zone codes")
    created_at: Optional[datetime] = Field(None, description="Database creation time")

    class Config:
        from_attributes = True


class AlertListResponse(BaseModel):
    """Schema for paginated alert list"""
    alerts: List[AlertResponse]
    total: int = Field(..., description="Total number of alerts")
    page: int = Field(default=1, description="Current page number", ge=1)
    page_size: int = Field(default=50, description="Items per page", ge=1, le=1000)
    has_more: bool = Field(..., description="Whether more pages exist")


class AlertStatsResponse(BaseModel):
    """Schema for alert statistics"""
    total_alerts: int = Field(..., description="Total alerts in database")
    active_alerts: int = Field(..., description="Currently active alerts")
    alerts_last_24h: int = Field(..., description="Alerts in last 24 hours")
    alerts_last_7d: int = Field(..., description="Alerts in last 7 days")
    by_severity: Dict[str, int] = Field(..., description="Count by severity")
    by_event_type: Dict[str, int] = Field(..., description="Count by event type")
    last_alert_time: Optional[datetime] = Field(None, description="Time of most recent alert")
