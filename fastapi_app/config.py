"""
FastAPI Configuration Settings
Uses Pydantic Settings for environment variable management
"""

import os
from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field, PostgresDsn


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Application
    app_name: str = "EAS Station FastAPI"
    environment: str = Field(default="development", env="ENVIRONMENT")
    debug: bool = Field(default=False, env="DEBUG")
    host: str = Field(default="0.0.0.0", env="HOST")
    fastapi_port: int = Field(default=8001, env="FASTAPI_PORT")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://eas:eas@db:5432/eas",
        env="DATABASE_URL"
    )

    # Redis
    redis_url: str = Field(
        default="redis://redis:6379/0",
        env="REDIS_URL"
    )

    # Security
    secret_key: str = Field(
        default="",
        env="SECRET_KEY"
    )
    access_token_expire_minutes: int = Field(default=30, env="ACCESS_TOKEN_EXPIRE_MINUTES")

    # CORS
    cors_origins: List[str] = Field(
        default=["*"],
        env="CORS_ORIGINS"
    )

    # Audio Service
    audio_service_url: str = Field(
        default="http://localhost:5002",
        env="AUDIO_SERVICE_URL"
    )

    # WebSocket
    websocket_ping_interval: int = Field(default=25, env="WS_PING_INTERVAL")
    websocket_ping_timeout: int = Field(default=60, env="WS_PING_TIMEOUT")

    class Config:
        env_file = ".env"
        case_sensitive = False


# Create global settings instance
settings = Settings()
