"""Configuration settings for the API."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Settings:
    """Application settings."""

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL")

    # API
    API_TITLE: str = "Vidik API"
    API_VERSION: str = "0.1.0"
    API_DESCRIPTION: str = "REST API for Vidik news aggregation platform"

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Environment
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"


settings = Settings()
